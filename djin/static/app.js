// All external text is inserted with textContent so retrieved content can never inject markup.
const chat = document.getElementById("chat");
const approvalsPanel = document.getElementById("approvals");
const approvalList = document.getElementById("approval-list");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const sendLabel = sendButton.querySelector(".label");
const statusBar = document.getElementById("status");
const sessionId = document.getElementById("session-id");
const modelCard = document.getElementById("model-card");
const connections = document.getElementById("connections");
const toolList = document.getElementById("tool-list");
const toolCount = document.getElementById("tool-count");

const SVG_NS = "http://www.w3.org/2000/svg";

let conversationId = null;
let busy = false;
let suggestions = [];

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function icon(name) {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS(SVG_NS, "use");
  use.setAttribute("href", `#i-${name}`);
  svg.appendChild(use);
  return svg;
}

function scrollToEnd() {
  chat.scrollTop = chat.scrollHeight;
}

function clearEmptyState() {
  const empty = chat.querySelector(".empty");
  if (empty) empty.remove();
}

function messageShell(role, label) {
  const wrapper = el("div", `msg ${role}`);
  if (role === "assistant") {
    const mark = el("span", "mark");
    mark.appendChild(icon("lamp"));
    wrapper.appendChild(mark);
  }
  wrapper.appendChild(el("span", "sr-only", label));
  const body = el("div", "body");
  wrapper.appendChild(body);
  return { wrapper, body };
}

function addMessage(role, text) {
  clearEmptyState();
  const label = role === "user" ? "You" : role === "error" ? "Error" : "Djin";
  const { wrapper, body } = messageShell(role, label);
  if (role === "assistant") body.appendChild(renderMarkdown(text));
  else body.textContent = text;
  chat.appendChild(wrapper);
  scrollToEnd();
}

let stream = null;

function beginAssistant() {
  if (!stream) {
    hideThinking();
    clearEmptyState();
    const { wrapper, body } = messageShell("assistant", "Djin");
    wrapper.classList.add("streaming");
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

// The gap between sending and the first token can be seconds long when tools run,
// so the wait gets its own row rather than an empty transcript.
let thinkingRow = null;

function showThinking() {
  if (thinkingRow) return;
  clearEmptyState();
  thinkingRow = el("div", "thinking");
  thinkingRow.append(el("i"), el("i"), el("i"), el("span", null, "Thinking"));
  chat.appendChild(thinkingRow);
  scrollToEnd();
}

function hideThinking() {
  if (!thinkingRow) return;
  thinkingRow.remove();
  thinkingRow = null;
}

const STATE_TEXT = {
  running: "running",
  ok: "done",
  error: "failed",
  pending: "awaiting approval",
  skipped: "declined",
};

const activityRows = new Map();

function fillActivity(node, event) {
  const state = STATE_TEXT[event.status] || event.status;
  node.replaceChildren(
    el("span", `dot risk-${event.risk}`),
    el("span", "tool-name", event.tool),
    el("span", "state", `${event.risk} · ${state}`)
  );
  node.classList.toggle("running", event.status === "running");
  node.classList.toggle("failed", event.status === "error");
}

function upsertActivity(event) {
  hideThinking();
  clearEmptyState();
  let node = event.status === "running" ? null : activityRows.get(event.tool);
  if (!node) {
    node = el("div", "activity");
    chat.appendChild(node);
    activityRows.set(event.tool, node);
  }
  fillActivity(node, event);
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
    const meta = el("div", "meta");
    meta.append(
      el("span", `dot risk-${action.risk}`),
      el("span", null, action.tool_name),
      el("span", `tag risk-${action.risk}`, action.risk)
    );
    card.appendChild(meta);
    card.appendChild(el("pre", null, action.preview));

    const buttons = el("div", "buttons");
    const approve = el("button", "approve");
    approve.type = "button";
    approve.append(icon("check"), el("span", null, "Approve"));
    approve.onclick = () => decide(action.id, true);
    const reject = el("button", "reject");
    reject.type = "button";
    reject.append(icon("close"), el("span", null, "Reject"));
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
  sendButton.classList.toggle("is-busy", value);
  sendLabel.textContent = value ? "Working" : "Send";
  if (value) showThinking();
  else hideThinking();
}

function handleEvent(event) {
  switch (event.type) {
    case "start":
      if (event.conversation_id !== conversationId) {
        conversationId = event.conversation_id;
        sessionId.textContent = String(conversationId).slice(0, 8);
      }
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
      hideThinking();
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
  autoGrow();
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
    loadSessions();
  }
}

function autoGrow() {
  input.style.height = "auto";
  input.style.height = `${Math.min(input.scrollHeight, 220)}px`;
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage(input.value.trim(), false);
});

input.addEventListener("input", autoGrow);

input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

// ------------------------------------------------------------------ sessions

const sessionList = document.getElementById("session-list");
const newSessionButton = document.getElementById("new-session");
const toolRisk = new Map();
const RELATIVE = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const STEPS = [
  ["minute", 60_000],
  ["hour", 3_600_000],
  ["day", 86_400_000],
  ["week", 604_800_000],
  ["month", 2_592_000_000],
  ["year", 31_536_000_000],
];

function relativeTime(iso) {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) return "";
  const elapsed = Date.now() - then;
  if (elapsed < 60_000) return "just now";
  let [unit, size] = STEPS[0];
  for (const [nextUnit, nextSize] of STEPS) {
    if (elapsed < nextSize) break;
    [unit, size] = [nextUnit, nextSize];
  }
  return RELATIVE.format(-Math.round(elapsed / size), unit);
}

function renderSessions(sessions) {
  sessionList.replaceChildren();
  if (!sessions.length) {
    sessionList.appendChild(el("li", "session-empty", "No saved sessions yet."));
    return;
  }

  for (const session of sessions) {
    const row = el("li", `session${session.id === conversationId ? " is-active" : ""}`);

    const open = el("button", "session-open");
    open.type = "button";
    open.append(
      el("span", "session-title", session.title || "Untitled"),
      el("span", "session-when", relativeTime(session.updated_at))
    );
    open.onclick = () => loadSession(session.id);

    const remove = el("button", "session-del");
    remove.type = "button";
    remove.title = "Delete this session";
    remove.append(icon("trash"), el("span", "sr-only", `Delete ${session.title || "session"}`));
    remove.onclick = () => armDelete(row, session);

    row.append(open, remove);
    sessionList.appendChild(row);
  }
}

// Deleting a transcript cannot be undone, so the row asks first rather than a dialog.
function armDelete(row, session) {
  const previous = [...row.children];
  row.classList.add("confirming");

  const label = el("span", "confirm-label", "Delete?");
  const yes = el("button", "confirm-yes", "Delete");
  yes.type = "button";
  yes.onclick = () => deleteSession(session.id);
  const no = el("button", "confirm-no", "Keep");
  no.type = "button";
  no.onclick = () => {
    row.classList.remove("confirming");
    row.replaceChildren(...previous);
  };

  row.replaceChildren(label, yes, no);
  yes.focus();
}

async function deleteSession(id) {
  try {
    const response = await fetch(`/api/conversations/${id}`, { method: "DELETE" });
    if (!response.ok) throw new Error(`Could not delete the session (${response.status})`);
  } catch (error) {
    addMessage("error", error.message);
    return;
  }
  if (id === conversationId) startNewSession();
  await loadSessions();
}

function startNewSession() {
  conversationId = null;
  sessionId.textContent = "new";
  stream = null;
  activityRows.clear();
  renderApprovals([]);
  chat.replaceChildren();
  renderEmptyState(suggestions);
  input.focus();
}

function toolStatuses(messages) {
  const statuses = new Map();
  for (const message of messages) {
    if (message.role !== "tool" || !message.tool_call_id) continue;
    const text = message.content || "";
    const failed = /^(tool error|invalid arguments)/i.test(text) || / failed: /.test(text);
    statuses.set(message.tool_call_id, failed ? "error" : "ok");
  }
  return statuses;
}

function replay(messages) {
  chat.replaceChildren();
  activityRows.clear();
  const statuses = toolStatuses(messages);

  for (const message of messages) {
    if (message.role === "user") {
      addMessage("user", message.content || "");
    } else if (message.role === "assistant") {
      if ((message.content || "").trim()) addMessage("assistant", message.content);
      for (const call of message.tool_calls || []) {
        const name = (call.function && call.function.name) || "tool";
        const node = el("div", "activity");
        fillActivity(node, {
          tool: name,
          risk: toolRisk.get(name) || "read",
          status: statuses.get(call.id) || "ok",
        });
        chat.appendChild(node);
      }
    }
  }
  if (!chat.children.length) renderEmptyState(suggestions);
  scrollToEnd();
}

async function loadSession(id) {
  if (busy) return;
  try {
    const response = await fetch(`/api/conversations/${id}`);
    if (!response.ok) throw new Error(`Could not open that session (${response.status})`);
    const data = await response.json();
    conversationId = id;
    sessionId.textContent = id.slice(0, 8);
    replay(data.messages);
    renderApprovals(data.pending);
    await loadSessions();
    input.focus();
  } catch (error) {
    addMessage("error", error.message);
  }
}

async function loadSessions() {
  try {
    const response = await fetch("/api/conversations?limit=40");
    renderSessions(await response.json());
  } catch {
    sessionList.replaceChildren(el("li", "session-empty", "Sessions unavailable."));
  }
}

newSessionButton.addEventListener("click", startNewSession);

// ------------------------------------------------------------------ session panel

const CONNECTIONS = [
  { key: "google", glyph: "mail", label: "Google" },
  { key: "reddit", glyph: "chat", label: "Reddit" },
  { key: "search", glyph: "search", label: "Web search" },
  { key: "notes", glyph: "note", label: "Notes" },
  { key: "scheduler", glyph: "history", label: "Schedules" },
  { key: "notifications", glyph: "send", label: "Push" },
];

function connectionState(key, info) {
  if (!info) return { on: false, text: "off" };
  if (key === "search") {
    return info.configured
      ? { on: true, text: info.provider || "ready" }
      : { on: false, text: "not set up" };
  }
  if (key === "notes") return { on: true, text: "local" };
  if (key === "scheduler") {
    if (!info.configured) return { on: false, text: "disabled" };
    if (!info.connected) return { on: false, text: "stopped" };
    const count = info.enabled_count || 0;
    return { on: true, text: `${count} active` };
  }
  if (key === "notifications") {
    return info.configured
      ? { on: true, text: info.provider || "ready" }
      : { on: false, text: "not set up" };
  }
  if (info.connected) return { on: true, text: "linked" };
  return { on: false, text: info.configured ? "sign in" : "not set up" };
}

function renderSession(data) {
  const name = el("div", "model-name", data.model);
  const tags = el("div", "tags");
  tags.appendChild(el("span", "tag", data.provider));
  tags.appendChild(
    el("span", data.auto_approve_write ? "tag is-warn" : "tag", data.auto_approve_write ? "writes: auto" : "writes: ask")
  );
  if (!data.llm_key_present) tags.appendChild(el("span", "tag is-bad", "no API key"));
  modelCard.replaceChildren(name, tags);

  connections.replaceChildren();
  for (const { key, glyph, label } of CONNECTIONS) {
    const info = data.integrations[key];
    const { on, text } = connectionState(key, info);
    const row = el("li", `conn ${on ? "is-on" : "is-off"}`);
    row.append(icon(glyph), el("span", "conn-name", label), el("span", "conn-state", text));
    connections.appendChild(row);
  }

  toolCount.textContent = String(data.tools.length);
  toolList.replaceChildren();
  toolRisk.clear();
  for (const tool of data.tools) {
    toolRisk.set(tool.name, tool.risk);
    const item = el("li", "tool");
    item.title = `${tool.risk} · ${tool.description}`;
    item.append(el("span", `dot risk-${tool.risk}`), el("span", "tool-name", tool.name));
    toolList.appendChild(item);
  }

  statusBar.replaceChildren();
  const pill = el("span", data.llm_key_present ? "pill is-live" : "pill is-bad");
  pill.append(el("span", "dot"), el("span", null, data.llm_key_present ? "ready" : "no API key"));
  statusBar.appendChild(pill);
}

function suggestionsFor(data) {
  const out = [];
  const { google, search, reddit, scheduler } = data.integrations;
  if (google && google.connected) out.push("Digest my unread mail", "What is on my calendar tomorrow?");
  if (scheduler && scheduler.connected) out.push("Schedule a weekday briefing at 7:00 AM");
  if (search && search.configured) out.push("Find this week's coverage of the EU AI Act");
  if (reddit && reddit.connected) out.push("What is r/LocalLLaMA arguing about today?");
  out.push("Which tools can you run?", "Start a note called Scratch");
  return out.slice(0, 4);
}

function renderEmptyState(prompts) {
  const box = el("div", "empty");
  const mark = el("div", "empty-mark");
  mark.appendChild(icon("lamp"));
  box.append(
    mark,
    el("h2", null, "What should I dig into?"),
    el("p", null, "Mail, calendar, the web, Reddit and your notes — read freely, write only with your say-so.")
  );

  const row = el("div", "suggestions");
  for (const text of prompts) {
    const chip = el("button", "chip", text);
    chip.type = "button";
    chip.onclick = () => {
      input.value = text;
      autoGrow();
      input.focus();
    };
    row.appendChild(chip);
  }
  box.appendChild(row);
  chat.appendChild(box);
}

async function loadStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    renderSession(data);
    suggestions = suggestionsFor(data);
    if (!chat.children.length) renderEmptyState(suggestions);
  } catch {
    modelCard.replaceChildren(el("div", "model-name", "status unavailable"));
    connections.replaceChildren();
    statusBar.replaceChildren(el("span", "pill is-bad", "offline"));
  }
}

loadStatus();
loadSessions();
DjinVoice.init({ send: sendMessage, isBusy: () => busy });
autoGrow();
input.focus();

