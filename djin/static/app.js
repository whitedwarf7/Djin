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
  wrapper.appendChild(el("div", "body", text));
  chat.appendChild(wrapper);
  scrollToEnd();
}

function addActivity(item) {
  const node = el("div", "activity");
  node.appendChild(el("span", `risk-${item.risk}`, `${item.tool} [${item.risk}]`));
  node.appendChild(document.createTextNode(` ${item.status} · ${item.approval}`));
  chat.appendChild(node);
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

function handleResult(result) {
  conversationId = result.conversation_id || conversationId;
  (result.activity || []).forEach(addActivity);
  if (result.reply) addMessage("assistant", result.reply);
  if (result.error) addMessage("error", result.error);
  renderApprovals(result.pending);
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `Request failed (${response.status})`);
  return data;
}

async function decide(actionId, approve) {
  if (busy) return;
  setBusy(true);
  try {
    handleResult(await postJson(`/api/actions/${actionId}/decision`, { approve }));
  } catch (error) {
    addMessage("error", error.message);
  } finally {
    setBusy(false);
  }
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = input.value.trim();
  if (!message || busy) return;

  addMessage("user", message);
  input.value = "";
  setBusy(true);
  try {
    handleResult(await postJson("/api/chat", { message, conversation_id: conversationId }));
  } catch (error) {
    addMessage("error", error.message);
  } finally {
    setBusy(false);
    input.focus();
  }
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
input.focus();
