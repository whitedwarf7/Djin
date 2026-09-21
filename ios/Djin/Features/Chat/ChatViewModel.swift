import Foundation
import Combine

@MainActor
final class ChatViewModel: ObservableObject {
    @Published private(set) var timeline: [TimelineItem] = []
    @Published private(set) var pendingActions: [PendingAction] = []
    @Published private(set) var conversations: [ConversationSummary] = []
    @Published private(set) var serverStatus: ServerStatus?
    @Published private(set) var activeConversationID: String?
    @Published private(set) var isBusy = false
    @Published private(set) var isLoadingConversation = false
    @Published private(set) var isLoadingSessions = false
    @Published var bannerMessage: String?
    @Published private(set) var sessionExpired = false

    private let client: APIClient
    private var activeAssistantID: UUID?
    private var toolRisks: [String: String] = [:]
    private var didLoad = false
    private var navigationGeneration = 0

    init(client: APIClient) {
        self.client = client
    }

    var suggestions: [String] {
        guard let serverStatus else {
            return ["Which tools can you run?", "Start a note called Scratch"]
        }

        var values: [String] = []
        if serverStatus.integrations.google.connected == true {
            values.append("Digest my unread mail")
            values.append("What is on my calendar tomorrow?")
        }
        if serverStatus.integrations.scheduler.connected == true {
            values.append("Schedule a weekday briefing at 7:00 AM")
        }
        if serverStatus.integrations.search.configured == true {
            values.append("Find this week's coverage of the EU AI Act")
        }
        values.append("Which tools can you run?")
        values.append("Start a note called Scratch")
        return Array(values.prefix(4))
    }

    var statusText: String {
        guard let serverStatus else {
            return "Connecting"
        }
        return serverStatus.llmKeyPresent ? "Ready" : "No API key"
    }

    var isReady: Bool {
        serverStatus?.llmKeyPresent == true
    }

    var showsThinking: Bool {
        isBusy && activeAssistantID == nil
    }

    func loadInitialData() async {
        guard !didLoad else {
            return
        }
        didLoad = true
        await refreshStatus()
        await refreshConversations()
    }

    func refreshStatus() async {
        do {
            let status = try await client.status()
            serverStatus = status
            toolRisks = Dictionary(uniqueKeysWithValues: status.tools.map { ($0.name, $0.risk) })
        } catch {
            record(error, messagePrefix: "Could not load server status")
        }
    }

    func refreshConversations(showError: Bool = true) async {
        isLoadingSessions = true
        defer { isLoadingSessions = false }
        do {
            conversations = try await client.conversations()
        } catch {
            if showError {
                record(error, messagePrefix: "Could not load sessions")
            }
        }
    }

    func startNewConversation() {
        guard !isBusy else {
            return
        }
        navigationGeneration += 1
        isLoadingConversation = false
        activeConversationID = nil
        activeAssistantID = nil
        pendingActions = []
        timeline = []
        bannerMessage = nil
    }

    func send(_ value: String) async {
        let message = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !isBusy, pendingActions.isEmpty else {
            return
        }

        timeline.append(TimelineItem(kind: .user, content: message))
        activeAssistantID = nil
        bannerMessage = nil
        isBusy = true

        do {
            let request = ChatRequest(
                message: message,
                conversationID: activeConversationID,
                voice: false
            )
            for try await event in try client.streamChat(request) {
                apply(event)
            }
        } catch {
            appendError(error.localizedDescription)
            recordUnauthorized(error)
        }

        activeAssistantID = nil
        isBusy = false
        await refreshConversations(showError: false)
    }

    func decide(_ action: PendingAction, approve: Bool) async {
        guard !isBusy else {
            return
        }

        pendingActions.removeAll { $0.id == action.id }
        activeAssistantID = nil
        bannerMessage = nil
        isBusy = true

        do {
            let request = DecisionRequest(approve: approve, voice: false)
            for try await event in try client.streamDecision(actionID: action.id, request: request) {
                apply(event)
            }
        } catch {
            appendError(error.localizedDescription)
            recordUnauthorized(error)
            if let activeConversationID {
                await loadConversation(id: activeConversationID, showLoadingState: false)
            }
        }

        activeAssistantID = nil
        isBusy = false
        await refreshConversations(showError: false)
    }

    func loadConversation(id: String, showLoadingState: Bool = true) async {
        guard (!isBusy || !showLoadingState) && !isLoadingConversation else {
            return
        }
        navigationGeneration += 1
        let requestGeneration = navigationGeneration
        if showLoadingState {
            isLoadingConversation = true
        }
        defer {
            if navigationGeneration == requestGeneration {
                isLoadingConversation = false
            }
        }

        do {
            let detail = try await client.conversation(id: id)
            guard navigationGeneration == requestGeneration else {
                return
            }
            activeConversationID = detail.conversationID
            activeAssistantID = nil
            pendingActions = detail.pending
            timeline = replay(detail.messages, pending: detail.pending)
            bannerMessage = nil
        } catch {
            guard navigationGeneration == requestGeneration else {
                return
            }
            record(error, messagePrefix: "Could not open that session")
        }
    }

    func deleteConversation(_ conversation: ConversationSummary) async {
        guard !isBusy, !isLoadingConversation else {
            return
        }
        do {
            try await client.deleteConversation(id: conversation.id)
            conversations.removeAll { $0.id == conversation.id }
            if activeConversationID == conversation.id {
                startNewConversation()
            }
        } catch {
            record(error, messagePrefix: "Could not delete that session")
        }
    }

    private func apply(_ event: StreamEvent) {
        switch event.type {
        case "start":
            if let conversationID = event.conversationID {
                activeConversationID = conversationID
            }
        case "delta":
            appendAssistantDelta(event.content ?? "")
        case "message_end":
            activeAssistantID = nil
        case "tool":
            activeAssistantID = nil
            upsertTool(event)
        case "pending":
            activeAssistantID = nil
            pendingActions = event.actions ?? []
        case "error":
            activeAssistantID = nil
            appendError(event.message ?? "The turn failed.")
        case "done":
            activeAssistantID = nil
        default:
            break
        }
    }

    private func appendAssistantDelta(_ content: String) {
        guard !content.isEmpty else {
            return
        }
        if let activeAssistantID,
           let index = timeline.firstIndex(where: { $0.id == activeAssistantID }) {
            timeline[index].content += content
            return
        }

        let item = TimelineItem(kind: .assistant, content: content)
        activeAssistantID = item.id
        timeline.append(item)
    }

    private func upsertTool(_ event: StreamEvent) {
        let name = event.tool ?? "tool"
        let state = event.status ?? "running"
        let matchingIndex = timeline.lastIndex(where: { item in
            guard item.kind == .tool else {
                return false
            }
            if let toolCallID = event.toolCallID {
                return item.toolCallID == toolCallID
            }
            return item.toolName == name && (item.status == "running" || item.status == "pending")
        })
        if let index = matchingIndex {
            timeline[index].status = state
            timeline[index].risk = event.risk ?? timeline[index].risk
            timeline[index].content = event.summary ?? ""
            timeline[index].toolCallID = event.toolCallID ?? timeline[index].toolCallID
            return
        }

        timeline.append(
            TimelineItem(
                kind: .tool,
                content: event.summary ?? "",
                toolName: name,
                risk: event.risk ?? "read",
                status: state,
                toolCallID: event.toolCallID
            )
        )
    }

    private func appendError(_ message: String) {
        timeline.append(TimelineItem(kind: .error, content: message))
    }

    private func replay(
        _ messages: [StoredMessage],
        pending: [PendingAction]
    ) -> [TimelineItem] {
        var resultByCallID: [String: String] = [:]
        for message in messages where message.role == "tool" {
            if let id = message.toolCallID {
                resultByCallID[id] = message.content ?? ""
            }
        }
        let pendingIDs = Set(pending.map(\.toolCallID))
        var items: [TimelineItem] = []

        for message in messages {
            if message.role == "user" {
                items.append(TimelineItem(kind: .user, content: message.content ?? ""))
                continue
            }
            guard message.role == "assistant" else {
                continue
            }

            if let content = message.content, !content.trimmingCharacters(in: .whitespaces).isEmpty {
                items.append(TimelineItem(kind: .assistant, content: content))
            }
            for call in message.toolCalls ?? [] {
                let result = call.id.flatMap { resultByCallID[$0] }
                let storedStatus = call.id.flatMap { callID in
                    messages.first(where: {
                        $0.role == "tool" && $0.toolCallID == callID
                    })?.toolStatus
                }
                let state: String
                if let storedStatus {
                    state = storedStatus
                } else if let callID = call.id, pendingIDs.contains(callID) {
                    state = "pending"
                } else {
                    state = inferredStatus(from: result)
                }
                items.append(
                    TimelineItem(
                        kind: .tool,
                        content: result ?? "",
                        toolName: call.function.name,
                        risk: toolRisks[call.function.name] ?? "read",
                        status: state,
                        toolCallID: call.id
                    )
                )
            }
        }
        return items
    }

    private func inferredStatus(from result: String?) -> String {
        guard let result else {
            return "unknown"
        }
        let normalized = result.lowercased()
        if normalized.hasPrefix("tool error:")
            || normalized.hasPrefix("invalid arguments")
            || normalized.hasPrefix("could not parse")
            || normalized.hasPrefix("unknown tool")
            || normalized.contains(" failed: ") {
            return "error"
        }
        if normalized.hasPrefix("tool blocked by") {
            return "blocked"
        }
        if normalized.hasPrefix("the user rejected") {
            return "skipped"
        }
        return "ok"
    }

    private func record(_ error: Error, messagePrefix: String) {
        bannerMessage = "\(messagePrefix). \(error.localizedDescription)"
        recordUnauthorized(error)
    }

    private func recordUnauthorized(_ error: Error) {
        if let apiError = error as? APIError,
           case .unauthorized = apiError {
            sessionExpired = true
        }
    }
}