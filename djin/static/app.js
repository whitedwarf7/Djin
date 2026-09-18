// All external text is inserted with textContent so retrieved content can never inject markup.
const chat = document.getElementById("chat");
const approvalsPanel = document.getElementById("approvals");
const approvalList = document.getElementById("approval-list");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const statusBar = document.getElementById("status");

let conversationId = null;
let busy = false;

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollToEnd() {
  chat.scrollTop = chat.scrollHeight;
}

function addMessage(role, text) {
  const wrapper = el("div", `msg ${role}`);
  wrapper.appendChild(el("div", "who", role));
  const body = el("div", "body");
  if (role === "assistant") body.appendChild(renderMarkdown(text));
  else body.textContent = text;
  wrapper.appendChild(body);
  chat.appendChild(wrapper);
  scrollToEnd();
}

let stream = null;

function beginAssistant() {
  if (!stream) {
    const wrapper = el("div", "msg assistant streaming");
    wrapper.appendChild(el("div", "who", "assistant"));
    const body = el("div", "body");
    wrapper.appendChild(body);
    chat.appendChild(wrapper);
    stream = { wrapper, body, raw: "", frame: 0 };
    scrollToEnd();
  }
  return stream;
}

function pushDelta(text) {
  const target = beginAssistant();
  target.raw += text;
  if (target.frame) return;
  // Re-render at most once per frame; markdown is reparsed from the full text each time.
  target.frame = requestAnimationFrame(() => {
    target.frame = 0;
    target.body.replaceChildren(renderMarkdown(target.raw));
    scrollToEnd();
  });
}

function endAssistant() {
  if (!stream) return;
  if (stream.frame) cancelAnimationFrame(stream.frame);
  if (stream.raw.trim()) {
    stream.body.replaceChildren(renderMarkdown(stream.raw));
    stream.wrapper.classList.remove("streaming");
  } else {
    stream.wrapper.remove();
  }
  stream = null;
  scrollToEnd();
}

const activityRows = new Map();

function upsertActivity(event) {
  let node = event.status === "running" ? null : activityRows.get(event.tool);
  if (!node) {
    node = el("div", "activity");
    chat.appendChild(node);
    activityRows.set(event.tool, node);
  }

  node.replaceChildren();
  node.appendChild(el("span", `risk-${event.risk}`, `${event.tool} [${event.risk}]`));
  node.appendChild(
    document.createTextNode(
      event.status === "running"
        ? " running…"
        : ` ${event.status}${event.approval ? " · " + event.approval : ""}`
    )
  );
  node.classList.toggle("running", event.status === "running");
  scrollToEnd();
}

function renderApprovals(pending) {
  approvalList.replaceChildren();
  if (!pending || pending.length === 0) {
    approvalsPanel.classList.add("hidden");
    return;
  }

  for (const action of pending) {
    const card = el("div", "approval");
    card.appendChild(el("div", "meta", `${action.tool_name} · risk: ${action.risk}`));
    card.appendChild(el("pre", null, action.preview));

    const buttons = el("div", "buttons");
    const approve = el("button", "approve", "Approve");
    approve.onclick = () => decide(action.id, true);
    const reject = el("button", "reject", "Reject");
    reject.onclick = () => decide(action.id, false);
    buttons.append(approve, reject);
    card.appendChild(buttons);
    approvalList.appendChild(card);
  }
  approvalsPanel.classList.remove("hidden");
}

function setBusy(value) {
  busy = value;
  sendButton.disabled = value;
  sendButton.textContent = value ? "Working…" : "Send";
}

function handleEvent(event) {
  switch (event.type) {
    case "start":
      conversationId = event.conversation_id;
      break;
    case "delta":
      pushDelta(event.content || "");
      break;
    case "message_end":
      endAssistant();
      break;
    case "tool":
      endAssistant();
      upsertActivity(event);
      break;
    case "pending":
      renderApprovals(event.actions);
      break;
    case "error":
      endAssistant();
      addMessage("error", event.message);
      break;
    case "done":
      endAssistant();
      break;
  }
  DjinVoice.handleEvent(event);
}

async function streamRequest(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.detail || `Request failed (${response.status})`);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const frames = buffer.split("\n\n");
    buffer = frames.pop();
    for (const frame of frames) {
      const line = frame.split("\n").find((part) => part.startsWith("data:"));
      if (line) handleEvent(JSON.parse(line.slice(5).trim()));
    }
  }
}

async function decide(actionId, approve) {
  if (busy) return;
  renderApprovals([]);
  setBusy(true);
  try {
    await streamRequest(`/api/actions/${actionId}/decision/stream`, {
      approve,
      voice: DjinVoice.isVoiceTurn(),
    });
  } catch (error) {
    addMessage("error", error.message);
  } finally {
    endAssistant();
    setBusy(false);
    DjinVoice.turnEnded();
  }
}

async function sendMessage(message, spoken) {
  if (!message || busy) return;

  addMessage("user", message);
  input.value = "";
  activityRows.clear();
  renderApprovals([]);
  DjinVoice.setVoiceTurn(Boolean(spoken));
  setBusy(true);
  try {
    await streamRequest("/api/chat/stream", {
      message,
      conversation_id: conversationId,
      voice: Boolean(spoken),
    });
  } catch (error) {
    addMessage("error", error.message);
  } finally {
    endAssistant();
    setBusy(false);
    DjinVoice.turnEnded();
    if (!spoken) input.focus();
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value.trim(), false);
});

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    statusBar.replaceChildren();

    const model = el("span", null, `${data.provider}:${data.model} `);
    statusBar.appendChild(model);
    if (!data.llm_key_present) statusBar.appendChild(el("span", "bad", "[no API key] "));

    for (const [name, info] of Object.entries(data.integrations)) {
      const connected = info.connected !== undefined ? info.connected : info.configured;
      const badge = el("span", connected ? "good" : "bad", ` ${name}${connected ? "✓" : "✗"}`);
      statusBar.appendChild(badge);
    }
  } catch {
    statusBar.textContent = "status unavailable";
  }
}

loadStatus();
DjinVoice.init({ send: sendMessage, isBusy: () => busy });
input.focus();
