(() => {
  const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content || "";
  const messageList = document.getElementById("message-list");
  const approvalList = document.getElementById("approval-list");
  const form = document.getElementById("chat-form");
  const input = document.getElementById("message-input");
  const sendButton = document.getElementById("send-button");
  const welcomeState = document.getElementById("welcome-state");
  const typingRow = document.getElementById("typing-row");
  const activityLabel = document.getElementById("activity-label");
  const conversationScroll = document.getElementById("conversation-scroll");
  const pendingCount = document.getElementById("pending-count");

  if (!messageList || !form) return;

  const escapeText = (value) => String(value ?? "");

  function scrollToBottom() {
    conversationScroll.scrollTop = conversationScroll.scrollHeight;
  }

  function renderMessage(message) {
    if (message.role === "activity") {
      const activity = document.createElement("div");
      activity.className = "activity-event";
      const check = document.createElement("span");
      check.className = "activity-check";
      check.textContent = "✓";
      const text = document.createElement("span");
      text.textContent = escapeText(message.content);
      activity.append(check, text);
      messageList.append(activity);
      welcomeState.hidden = true;
      return activity;
    }
    const row = document.createElement("article");
    row.className = `message-row ${message.role === "user" ? "is-user" : "is-assistant"}`;
    const avatar = document.createElement("span");
    avatar.className = message.role === "user" ? "message-avatar user-avatar" : "message-avatar agent-avatar";
    avatar.textContent = message.role === "user" ? "Y" : "✳";
    avatar.setAttribute("aria-hidden", "true");
    const content = document.createElement("div");
    content.className = "message-content";
    const heading = document.createElement("div");
    heading.className = "message-heading";
    const author = document.createElement("strong");
    author.textContent = message.role === "user" ? "You" : "Threadline";
    const time = document.createElement("time");
    time.textContent = message.created_at ? new Date(message.created_at).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" }) : "Now";
    heading.append(author, time);
    const text = document.createElement("p");
    text.className = "message-text";
    text.textContent = escapeText(message.content);
    content.append(heading, text);
    row.append(avatar, content);
    messageList.append(row);
    welcomeState.hidden = true;
    return row;
  }

  function renderApproval(approval) {
    const card = document.createElement("section");
    card.className = `approval-card ${approval.status !== "pending" ? "approval-resolved" : ""}`;
    card.dataset.approvalId = approval.id;
    const header = document.createElement("div");
    header.className = "approval-card-header";
    const badge = document.createElement("span");
    badge.className = "approval-badge";
    badge.innerHTML = '<span class="approval-badge-dot"></span> SHEETS CHANGE';
    const state = document.createElement("span");
    state.className = `approval-status status-${approval.status}`;
    state.textContent = approval.status === "executed" ? "Completed" : approval.status === "rejected" ? "Rejected" : approval.status === "failed" ? "Could not complete" : approval.status === "executing" ? "Processing" : "Awaiting your review";
    header.append(badge, state);

    const title = document.createElement("h3");
    title.textContent = approval.summary || "Proposed spreadsheet change";
    const description = document.createElement("p");
    description.className = "approval-description";
    description.textContent = approval.status === "pending"
      ? "Review the proposed values. Nothing has been written yet."
      : approval.status === "executed"
        ? "This change was approved and sent to Google Sheets."
        : approval.status === "rejected"
          ? "No spreadsheet data was written."
          : approval.status === "failed"
            ? "The app did not confirm a successful write."
            : "The approval is being processed.";
    card.append(header, title, description);

    if (Array.isArray(approval.values) && approval.values.length) {
      const tableWrap = document.createElement("div");
      tableWrap.className = "approval-table-wrap";
      const table = document.createElement("table");
      const head = document.createElement("thead");
      const headRow = document.createElement("tr");
      const columns = Math.max(...approval.values.map((row) => Array.isArray(row) ? row.length : 0));
      for (let index = 0; index < columns; index += 1) {
        const th = document.createElement("th");
        th.textContent = `Column ${index + 1}`;
        headRow.append(th);
      }
      head.append(headRow);
      const body = document.createElement("tbody");
      for (const values of approval.values) {
        const tr = document.createElement("tr");
        for (let index = 0; index < columns; index += 1) {
          const td = document.createElement("td");
          td.textContent = escapeText(values?.[index] ?? "");
          tr.append(td);
        }
        body.append(tr);
      }
      table.append(head, body);
      tableWrap.append(table);
      card.append(tableWrap);
    }

    if (approval.status === "pending") {
      const actions = document.createElement("div");
      actions.className = "approval-actions";
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "reject-button";
      reject.textContent = "Reject";
      reject.addEventListener("click", () => resolveApproval(approval.id, "reject", reject, approve));
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "approve-button";
      approve.innerHTML = 'Approve changes <span aria-hidden="true">→</span>';
      approve.addEventListener("click", () => resolveApproval(approval.id, "approve", approve, reject));
      actions.append(reject, approve);
      card.append(actions);
    }
    approvalList.append(card);
    welcomeState.hidden = true;
    return card;
  }

  async function resolveApproval(id, action, clicked, other) {
    if (clicked.disabled) return;
    clicked.disabled = true;
    other.disabled = true;
    clicked.textContent = action === "approve" ? "Writing to Sheets…" : "Rejecting…";
    try {
      const response = await fetch(`/api/approvals/${id}/${action}`, {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken },
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail || "This approval could not be completed.");
      renderMessage({ role: "assistant", content: body.message, created_at: new Date().toISOString() });
      await loadHistory();
    } catch (error) {
      clicked.disabled = false;
      other.disabled = false;
      clicked.textContent = action === "approve" ? "Approve changes →" : "Reject";
      renderMessage({ role: "assistant", content: error.message || "This approval could not be completed." });
    }
  }

  function setActivity(text) {
    typingRow.hidden = !text;
    activityLabel.textContent = text;
    scrollToBottom();
  }

  function setSending(sending) {
    input.disabled = sending || !input.dataset.connected || !input.dataset.gemini;
    sendButton.disabled = sending || !input.dataset.connected || !input.dataset.gemini;
    form.setAttribute("aria-busy", String(sending));
  }

  async function loadStatus() {
    try {
      const response = await fetch("/api/status", { headers: { Accept: "application/json" } });
      const status = await response.json();
      const connected = Boolean(status.google?.connected);
      const gemini = Boolean(status.gemini?.configured);
      input.dataset.connected = String(connected);
      input.dataset.gemini = String(gemini);
      input.disabled = !connected || !gemini;
      sendButton.disabled = !connected || !gemini;
      const label = document.getElementById("connection-label");
      const chip = document.getElementById("connection-chip");
      if (connected) {
        label.textContent = "Google connected";
        chip.classList.add("is-connected");
        document.getElementById("gmail-state").innerHTML = '<span class="state-dot is-online"></span>Connected';
        document.getElementById("sheets-state").innerHTML = '<span class="state-dot is-online"></span>Connected';
      } else {
        label.textContent = "Google not connected";
        document.getElementById("gmail-state").innerHTML = '<span class="state-dot"></span>Not connected';
        document.getElementById("sheets-state").innerHTML = '<span class="state-dot"></span>Not connected';
      }
      if (!gemini && connected) label.textContent = "Gemini setup needed";
      if (!gemini || !connected) setActivity("");
      return status;
    } catch {
      const label = document.getElementById("connection-label");
      if (label) label.textContent = "Connection status unavailable";
    }
  }

  async function loadHistory() {
    const response = await fetch("/api/history", { headers: { Accept: "application/json" } });
    if (!response.ok) return;
    const data = await response.json();
    messageList.replaceChildren();
    approvalList.replaceChildren();
    (data.messages || []).forEach(renderMessage);
    (data.approvals || []).forEach(renderApproval);
    const count = (data.approvals || []).filter((item) => item.status === "pending").length;
    pendingCount.textContent = String(count);
    pendingCount.hidden = count === 0;
    scrollToBottom();
  }

  async function sendMessage(text) {
    const message = text.trim();
    if (!message || sendButton.disabled) return;
    renderMessage({ role: "user", content: message, created_at: new Date().toISOString() });
    input.value = "";
    input.style.height = "auto";
    setSending(true);
    setActivity("Checking your connected sources…");
    const historyPoll = window.setInterval(() => {
      loadHistory().catch(() => {});
    }, 900);
    try {
      const response = await fetch("/api/chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken,
          Accept: "application/json",
        },
        body: JSON.stringify({ message }),
      });
      const result = await response.json();
      typingRow.hidden = true;
      if (!response.ok) {
        renderMessage({ role: "assistant", content: result.detail || "The request could not be completed." });
      } else {
        renderMessage(result.message);
        (result.approvals || []).forEach(renderApproval);
      }
      await loadHistory();
    } catch {
      typingRow.hidden = true;
      renderMessage({ role: "assistant", content: "I couldn't reach the app service. Check that it is running, then try again." });
    } finally {
      window.clearInterval(historyPoll);
      setSending(false);
      input.focus();
      scrollToBottom();
    }
  }

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    sendMessage(input.value);
  });
  input.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });
  document.querySelectorAll("[data-prompt]").forEach((button) => {
    button.addEventListener("click", () => {
      if (input.disabled) {
        window.location.assign("/login");
        return;
      }
      input.value = button.dataset.prompt;
      form.requestSubmit();
    });
  });
  document.getElementById("disconnect-google")?.addEventListener("click", async () => {
    if (!window.confirm("Disconnect this Google account? Stored access will be removed.")) return;
    const response = await fetch("/auth/disconnect", {
      method: "POST",
      headers: { "X-CSRF-Token": csrfToken },
    });
    if (response.ok) window.location.reload();
  });

  loadStatus();
  loadHistory().catch(() => {});
})();