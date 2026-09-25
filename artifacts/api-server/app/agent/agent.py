from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from app.agent.prompts import SYSTEM_INSTRUCTION
from app.agent.tools import (
    TOOL_DECLARATIONS,
    call_tool,
    user_explicitly_requested_write,
)
from app.config import settings
from app.models import Message

logger = logging.getLogger(__name__)
MAX_TOOL_ROUNDS = 8
MAX_HISTORY_MESSAGES = 16


class AgentSetupError(RuntimeError):
    pass


def _client() -> genai.Client:
    if not settings.gemini_api_key:
        raise AgentSetupError("Add GEMINI_API_KEY to Replit Secrets to enable Gemini.")
    return genai.Client(api_key=settings.gemini_api_key)


def _generate(client: genai.Client, contents: list[Any], tools: list[dict[str, Any]]) -> Any:
    config = types.GenerateContentConfig(
        system_instruction=SYSTEM_INSTRUCTION,
        tools=[types.Tool(function_declarations=tools)],
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        max_output_tokens=8192,
    )
    for attempt in range(3):
        try:
            return client.models.generate_content(
                model=settings.gemini_model,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            status = getattr(exc, "status_code", None)
            if status not in {429, 500, 502, 503, 504} or attempt == 2:
                raise
            time.sleep(0.5 * (2**attempt))
    raise RuntimeError("Gemini request could not be completed.")


def run_agent(
    db: Session,
    user_id: int,
    conversation_id: int,
    current_message: str,
    on_activity: Callable[[str, dict[str, Any], dict[str, Any]], None] | None = None,
) -> tuple[str, list[int]]:
    client = _client()
    history = (
        db.query(Message)
        .filter_by(conversation_id=conversation_id)
        .order_by(Message.id.desc())
        .limit(MAX_HISTORY_MESSAGES)
        .all()
    )
    history.reverse()
    contents: list[Any] = [
        types.Content(
            role="user" if row.role == "user" else "model",
            parts=[types.Part.from_text(text=row.content)],
        )
        for row in history
        if row.role in {"user", "assistant"}
    ]
    if not contents or contents[-1].role != "user":
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=current_message)]))

    allow_write = user_explicitly_requested_write(current_message)
    tool_declarations = list(TOOL_DECLARATIONS)
    if not allow_write:
        tool_declarations = [
            declaration
            for declaration in tool_declarations
            if declaration["name"] not in {"append_sheet_row", "update_sheet"}
        ]

    approval_ids: list[int] = []
    for _ in range(MAX_TOOL_ROUNDS):
        response = _generate(client, contents, tool_declarations)
        if not response.candidates:
            raise RuntimeError("Gemini returned no response. Try again.")
        model_content = response.candidates[0].content
        contents.append(model_content)
        calls = [
            part.function_call
            for part in (model_content.parts or [])
            if getattr(part, "function_call", None) is not None
        ]
        if not calls:
            answer = response.text
            if answer:
                return answer, approval_ids
            raise RuntimeError("Gemini returned an empty response. Try again.")

        function_response_parts: list[Any] = []
        for function_call in calls:
            name = function_call.name
            if name not in {tool["name"] for tool in tool_declarations}:
                result: dict[str, Any] = {"error": "That tool is not available."}
            else:
                try:
                    result = call_tool(
                        db=db,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        name=name,
                        raw_args=dict(function_call.args or {}),
                        allow_write=allow_write,
                    on_activity=on_activity,
                    )
                    if result.get("approval_id"):
                        approval_ids.append(result["approval_id"])
                except Exception:
                    logger.exception("Gemini tool failed: %s", name)
                    result = {"error": "The requested action could not be prepared."}
            function_response_parts.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        id=function_call.id,
                        name=name,
                        response={"result": result},
                    )
                )
            )
        contents.append(types.Content(role="user", parts=function_response_parts))

    raise RuntimeError("The request required too many tool steps. Narrow the request and try again.")