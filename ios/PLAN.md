# Djin for iPhone plan

## High-level plan

### Phase 1: Native core

- Build a native SwiftUI iPhone app in this `ios` directory.
- Reuse the existing FastAPI server rather than duplicate agent or integration logic.
- Sign in with the server's bearer-token API and keep the token in the iOS Keychain.
- Support streamed chat, tool activity, explicit approvals, and conversation history.
- Make the server address configurable for the simulator and a physical iPhone.

### Phase 2: Mobile capabilities

- Add native speech recognition and speech playback after text chat is stable.
- Add deep links from scheduled-result notifications into a conversation.
- Add background-safe refresh where iOS permits it; the Mac-hosted Djin server must still be running.
- Improve Markdown presentation for tables and code blocks if real conversations require it.

### Phase 3: Hardening and distribution

- Exercise reconnect, timeout, token-expiry, and interrupted-stream scenarios.
- Add UI tests for sign-in, chat, approvals, sessions, Dynamic Type, and dark mode.
- Replace development HTTP with trusted HTTPS before using Djin outside a private local network.
- Prepare App Store metadata, privacy disclosures, signing, and TestFlight distribution if desired.

## Low-level plan

### Project and platform

- SwiftUI app with an iOS 17 deployment target.
- XcodeGen owns the generated `.xcodeproj`; source-controlled settings live in `project.yml`.
- No third-party runtime dependencies in the first release.
- System type styles, SF Symbols, safe-area APIs, and semantic colors provide native behavior.

### App state and security

- `SessionStore` owns the configured server URL and signed-in user.
- `KeychainStore` persists only the bearer token; `UserDefaults` persists the non-secret server URL.
- App launch validates a saved token with `GET /api/auth/me`.
- Sign-out clears local credentials even when the server is unreachable.

### Networking

- `APIClient` builds authenticated JSON requests against the selected Djin server.
- Login uses `POST /api/auth/login` and stores `access_token`.
- Chat uses `POST /api/chat/stream`.
- Approval decisions use `POST /api/actions/{id}/decision/stream`.
- `SSEDecoder` maps each `data:` frame into a typed `StreamEvent`.
- HTTP failures decode FastAPI's `detail` when available and preserve a useful recovery message.

### Chat feature

- `ChatViewModel` owns the active conversation, timeline, pending approvals, status, and busy state.
- User, assistant, tool, and error entries share a chronological timeline.
- Assistant deltas update one in-progress row without rebuilding prior messages.
- Sending is disabled while a turn runs or an approval is unresolved.
- Approval cards show tool name, risk, preview, and separate approve/reject controls.

### Sessions feature

- `GET /api/conversations` fills a native session list.
- `GET /api/conversations/{id}` reconstructs user/assistant messages and tool activity.
- Selecting a session returns to chat with the transcript and pending approvals restored.
- Delete uses `DELETE /api/conversations/{id}` behind a confirmation dialog.

### Quality gates

- Unit-test SSE decoding and representative API payload decoding on macOS.
- Run the existing Python test suite because the mobile client depends on its API behavior.
- Build and test with Xcode on a small and large iPhone simulator.
- Manually check light mode, dark mode, landscape, Dynamic Type, VoiceOver labels, and reduced motion.
- Test once on a physical iPhone over the same private network as the Mac.

## API boundary

The iPhone app remains a client. Gmail, Calendar, notes, scheduler, LLM keys, OAuth tokens, and the SQLite database stay in the Python service on the Mac. This keeps secrets and tool permissions in the existing trusted boundary and prevents two implementations from drifting.
