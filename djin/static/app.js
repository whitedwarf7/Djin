// All external text is inserted with textContent so retrieved content can never inject markup.
const chat = document.getElementById("chat");
const approvalsPanel = document.getElementById("approvals");
const approvalList = document.getElementById("approval-list");
const form = document.getElementById("composer");
const input = document.getElementById("input");
const sendButton = document.getElementById("send");
const sendLabel = sendButton.querySelector(".label");
const statusBar = document.getElementById("status");
const sessionHeading = document.getElementById("session-title");
const modelName = document.getElementById("model-name");
const connections = document.getElementById("connections");
const appShell = document.getElementById("app-shell");
const authView = document.getElementById("auth-view");
const authForm = document.getElementById("auth-form");
const authTitle = document.getElementById("auth-title");
const authLead = document.getElementById("auth-lead");
const authKicker = document.getElementById("auth-kicker");
const authUsername = document.getElementById("auth-username");
const authPassword = document.getElementById("auth-password");
const authPasswordHint = document.getElementById("auth-password-hint");
const authConfirm = document.getElementById("auth-confirm");
const authConfirmHint = document.getElementById("auth-confirm-hint");
const authConfirmField = document.getElementById("auth-confirm-field");
const passwordToggle = document.getElementById("toggle-password");
const confirmToggle = document.getElementById("toggle-confirm");
const authError = document.getElementById("auth-error");
const authSubmit = document.getElementById("auth-submit");
const authSubmitLabel = authSubmit.querySelector(".label");
const authProvision = document.getElementById("auth-provision");
const authProvisionStatus = document.getElementById("auth-provision-status");
const checkOwnerButton = document.getElementById("check-owner");
const authFootnote = document.getElementById("auth-footnote");
const accountName = document.getElementById("account-name");
const accountRole = document.getElementById("account-role");
const logoutButton = document.getElementById("logout");

const SVG_NS = "http://www.w3.org/2000/svg";
const nativeFetch = window.fetch.bind(window);

let conversationId = null;
let busy = false;
let suggestions = [];
let authMode = "login";
let appStarted = false;

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

function responseError(data, fallback) {
  if (typeof data.detail === "string") return data.detail;
  if (Array.isArray(data.detail) && data.detail.length) {
    return data.detail[0].msg;
  }
  return fallback;
}

function setPasswordVisibility(inputNode, button, visible, subject = "password") {
  inputNode.type = visible ? "text" : "password";
  const label = `${visible ? "Hide" : "Show"} ${subject}`;
  button.title = label;
  button.setAttribute("aria-label", label);
  button.querySelector("use").setAttribute("href", visible ? "#i-eye-off" : "#i-eye");
}

function updatePasswordFeedback() {
  if (authMode !== "register") return;
  const meetsLength = authPassword.value.length >= 12;
  authPasswordHint.textContent = meetsLength
    ? "Length requirement met."
    : "Use at least 12 characters.";
  authPasswordHint.className = `field-hint${meetsLength ? " is-valid" : ""}`;

  const confirmation = authConfirm.value;
  const matches = confirmation && confirmation === authPassword.value;
  authConfirmHint.textContent = !confirmation
    ? "Re-enter the same password."
    : matches ? "Passwords match." : "Passwords do not match.";
  authConfirmHint.className = `field-hint${confirmation ? matches ? " is-valid" : " is-invalid" : ""}`;
}

function showAuth(registrationRequired, message = "") {
  authMode = registrationRequired ? "register" : "login";
  if (appStarted) DjinVoice.deactivate();
  authView.dataset.mode = authMode;
  appShell.classList.add("hidden");
  authView.classList.remove("hidden");
  authForm.classList.remove("hidden");
  authProvision.classList.add("hidden");
  authFootnote.classList.remove("hidden");
  authTitle.textContent = registrationRequired ? "Create your owner account" : "Sign in";
  authKicker.textContent = registrationRequired ? "First run" : "Protected workspace";
  authLead.textContent = registrationRequired
    ? "Set the credentials you will use on this machine."
    : "Use your owner credentials to continue.";
  authConfirmField.classList.toggle("hidden", !registrationRequired);
  authConfirm.required = registrationRequired;
  authPassword.minLength = registrationRequired ? 12 : 1;
  authPassword.autocomplete = registrationRequired ? "new-password" : "current-password";
  authSubmitLabel.textContent = registrationRequired ? "Create account" : "Sign in";
  authError.textContent = message;
  authForm.reset();
  setPasswordVisibility(authPassword, passwordToggle, false);
  setPasswordVisibility(authConfirm, confirmToggle, false, "password confirmation");
  authPasswordHint.textContent = registrationRequired
    ? "Use at least 12 characters."
    : "Enter your account password.";
  authPasswordHint.className = "field-hint";
  authConfirmHint.textContent = "Re-enter the same password.";
  authConfirmHint.className = "field-hint";
  requestAnimationFrame(() => authUsername.focus());
}

function showProvisioning(message = "") {
  authMode = "provision";
  if (appStarted) DjinVoice.deactivate();
  authView.dataset.mode = authMode;
  appShell.classList.add("hidden");
  authView.classList.remove("hidden");
  authForm.classList.add("hidden");
  authProvision.classList.remove("hidden");
  authFootnote.classList.add("hidden");
  authKicker.textContent = "Host setup required";
  authTitle.textContent = "Create the owner locally";
  authLead.textContent = "Browser account creation is disabled through this address.";
  authProvisionStatus.textContent = message;
  requestAnimationFrame(() => checkOwnerButton.focus());
}

function setAuthBusy(value) {
  for (const control of authForm.querySelectorAll("input, button")) control.disabled = value;
  authForm.setAttribute("aria-busy", String(value));
  authSubmitLabel.textContent = value
    ? authMode === "register" ? "Creating…" : "Signing in…"
    : authMode === "register" ? "Create account" : "Sign in";
}

async function apiFetch(resource, options = {}) {
  const response = await nativeFetch(resource, { credentials: "same-origin", ...options });
  if (response.status === 401) showAuth(false, "Your session expired. Sign in again.");
  return response;
}

window.DjinAuth = { fetch: apiFetch };

passwordToggle.addEventListener("click", () => {
  setPasswordVisibility(authPassword, passwordToggle, authPassword.type === "password");
  authPassword.focus();
});

confirmToggle.addEventListener("click", () => {
  setPasswordVisibility(
    authConfirm,
    confirmToggle,
    authConfirm.type === "password",
    "password confirmation"
  );
  authConfirm.focus();
});

authPassword.addEventListener("input", updatePasswordFeedback);
authConfirm.addEventListener("input", updatePasswordFeedback);

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
  const key = event.tool_call_id || event.tool;
  let node = event.tool_call_id
    ? activityRows.get(key)
    : event.status === "running" ? null : activityRows.get(key);
  if (!node) {
    node = el("div", "activity");
    chat.appendChild(node);
    activityRows.set(key, node);
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
      }
      sessionHeading.textContent = event.title || "New session";
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
  const response = await apiFetch(url, {
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
    const response = await apiFetch(`/api/conversations/${id}`, { method: "DELETE" });
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
  sessionHeading.textContent = "New session";
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
    const failed = /^(tool error|invalid arguments|could not parse|unknown tool)/i.test(text)
      || / failed: /.test(text);
    const inferred = failed
      ? "error"
      : /^tool blocked by/i.test(text)
        ? "blocked"
        : /^the user rejected/i.test(text)
          ? "skipped"
          : "ok";
    statuses.set(message.tool_call_id, message._status || inferred);
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
          status: statuses.get(call.id) || "unknown",
        });
        chat.appendChild(node);
        activityRows.set(call.id || name, node);
      }
    }
  }
  if (!chat.children.length) renderEmptyState(suggestions);
  scrollToEnd();
}

async function loadSession(id) {
  if (busy) return;
  try {
    const response = await apiFetch(`/api/conversations/${id}`);
    if (!response.ok) throw new Error(`Could not open that session (${response.status})`);
    const data = await response.json();
    conversationId = id;
    sessionHeading.textContent = data.title || "Untitled session";
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
    const response = await apiFetch("/api/conversations?limit=40");
    if (!response.ok) throw new Error();
    renderSessions(await response.json());
  } catch {
    sessionList.replaceChildren(el("li", "session-empty", "Sessions unavailable."));
  }
}

newSessionButton.addEventListener("click", startNewSession);

// ------------------------------------------------------------------ session panel

const CONNECTIONS = [
  { key: "google", glyph: "mail", label: "Google" },
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
  modelName.textContent = data.model;
  modelName.title = `${data.provider} · ${data.model}`;

  connections.replaceChildren();
  for (const { key, glyph, label } of CONNECTIONS) {
    const info = data.integrations[key];
    const { on, text } = connectionState(key, info);
    const row = el("li", `conn ${on ? "is-on" : "is-off"}`);
    row.append(icon(glyph), el("span", "conn-name", label), el("span", "conn-state", text));
    connections.appendChild(row);
  }

  toolRisk.clear();
  for (const tool of data.tools) {
    toolRisk.set(tool.name, tool.risk);
  }

  statusBar.replaceChildren();
  const pill = el("span", data.llm_key_present ? "pill is-live" : "pill is-bad");
  pill.append(el("span", "dot"), el("span", null, data.llm_key_present ? "ready" : "no API key"));
  statusBar.appendChild(pill);
}

function suggestionsFor(data) {
  const out = [];
  const { google, search, scheduler } = data.integrations;
  if (google && google.connected) out.push("Digest my unread mail", "What is on my calendar tomorrow?");
  if (scheduler && scheduler.connected) out.push("Schedule a weekday briefing at 7:00 AM");
  if (search && search.configured) out.push("Find this week's coverage of the EU AI Act");
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
    el("p", null, "Mail, calendar, the web and your notes — read freely, write only with your say-so.")
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
    const response = await apiFetch("/api/status");
    if (!response.ok) throw new Error();
    const data = await response.json();
    renderSession(data);
    suggestions = suggestionsFor(data);
    if (!chat.children.length) renderEmptyState(suggestions);
  } catch {
    modelName.textContent = "Model unavailable";
    modelName.removeAttribute("title");
    connections.replaceChildren();
    statusBar.replaceChildren(el("span", "pill is-bad", "offline"));
  }
}

async function enterApp(user) {
  accountName.textContent = user.username;
  accountRole.textContent = user.role;
  authView.classList.add("hidden");
  appShell.classList.remove("hidden");

  if (!appStarted) {
    appStarted = true;
    DjinVoice.init({ send: sendMessage, isBusy: () => busy });
    autoGrow();
  }
  await Promise.all([loadStatus(), loadSessions()]);
  input.focus();
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.textContent = "";
  if (authMode === "register" && authPassword.value !== authConfirm.value) {
    authError.textContent = "Passwords do not match.";
    authConfirm.focus();
    return;
  }

  setAuthBusy(true);
  try {
    const endpoint = authMode === "register" ? "/api/auth/register" : "/api/auth/login";
    const response = await nativeFetch(endpoint, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        username: authUsername.value,
        password: authPassword.value,
      }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const message = responseError(data, `Sign-in failed (${response.status})`);
      if (authMode === "register" && (response.status === 403 || response.status === 409)) {
        await initialize(response.status === 409 ? "The owner account is ready. Sign in." : message);
        return;
      }
      throw new Error(message);
    }
    await enterApp(data.user);
  } catch (error) {
    authError.textContent = error.message;
  } finally {
    setAuthBusy(false);
  }
});

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    const response = await nativeFetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
    });
    if (response.status === 401) {
      showAuth(false, "Your session has ended. Sign in again.");
      return;
    }
    if (!response.ok) throw new Error(`Sign-out failed (${response.status})`);
    showAuth(false);
  } catch (error) {
    statusBar.replaceChildren(el("span", "pill is-bad", error.message));
  } finally {
    logoutButton.disabled = false;
  }
});

checkOwnerButton.addEventListener("click", async () => {
  checkOwnerButton.disabled = true;
  authProvisionStatus.textContent = "Checking…";
  await initialize("Owner account not found yet.");
  checkOwnerButton.disabled = false;
});

async function initialize(message = "") {
  try {
    const setupResponse = await nativeFetch("/api/auth/setup", { credentials: "same-origin" });
    if (!setupResponse.ok) throw new Error(`Setup check failed (${setupResponse.status})`);
    const setup = await setupResponse.json();
    if (setup.registration_required) {
      if (setup.registration_allowed) showAuth(true, message);
      else showProvisioning(message);
      return;
    }

    const meResponse = await nativeFetch("/api/auth/me", { credentials: "same-origin" });
    if (!meResponse.ok) {
      showAuth(false, message);
      return;
    }
    await enterApp(await meResponse.json());
  } catch (error) {
    showAuth(false, error.message);
  }
}

initialize();

