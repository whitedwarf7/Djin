import SwiftUI

struct SessionsView: View {
    @ObservedObject var model: ChatViewModel
    let onOpenChat: () -> Void
    let onNewChat: () -> Void

    @State private var pendingDeletion: ConversationSummary?
    @State private var showsDeleteConfirmation = false

    var body: some View {
        NavigationStack {
            Group {
                if model.conversations.isEmpty && !model.isLoadingSessions {
                    ContentUnavailableView(
                        "No sessions yet",
                        systemImage: "message",
                        description: Text("Start a conversation with Djin.")
                    )
                } else {
                    sessionList
                }
            }
            .background(DjinTheme.background)
            .navigationTitle("Sessions")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: onNewChat) {
                        Image(systemName: "square.and.pencil")
                    }
                    .disabled(model.isBusy)
                    .accessibilityLabel("New conversation")
                }
            }
            .overlay {
                if model.isLoadingSessions && model.conversations.isEmpty {
                    ProgressView("Loading sessions")
                }
            }
            .confirmationDialog(
                "Delete this conversation?",
                isPresented: $showsDeleteConfirmation,
                presenting: pendingDeletion
            ) { conversation in
                Button("Delete", role: .destructive) {
                    Task { await model.deleteConversation(conversation) }
                }
                Button("Cancel", role: .cancel) {}
            } message: { conversation in
                Text("\"\(conversation.title)\" will be removed. Its audit history is retained.")
            }
        }
    }

    private var sessionList: some View {
        List(model.conversations) { conversation in
            Button {
                Task {
                    await model.loadConversation(id: conversation.id)
                    if model.activeConversationID == conversation.id {
                        onOpenChat()
                    }
                }
            } label: {
                SessionRow(conversation: conversation)
            }
            .buttonStyle(.plain)
            .disabled(model.isBusy || model.isLoadingConversation)
            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                Button(role: .destructive) {
                    pendingDeletion = conversation
                    showsDeleteConfirmation = true
                } label: {
                    Label("Delete", systemImage: "trash")
                }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(DjinTheme.background)
        .refreshable {
            await model.refreshConversations()
        }
    }
}

private struct SessionRow: View {
    let conversation: ConversationSummary

    var body: some View {
        HStack(spacing: 12) {
            VStack(alignment: .leading, spacing: 5) {
                Text(conversation.title)
                    .font(.body.weight(.semibold))
                    .foregroundStyle(DjinTheme.primaryText)
                    .lineLimit(2)
                Text(metadata)
                    .font(.caption)
                    .foregroundStyle(DjinTheme.secondaryText)
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            Image(systemName: "chevron.right")
                .font(.caption.weight(.bold))
                .foregroundStyle(DjinTheme.secondaryText)
                .accessibilityHidden(true)
        }
        .frame(minHeight: 52)
        .contentShape(Rectangle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(conversation.title), \(metadata)")
    }

    private var metadata: String {
        let count = conversation.messageCount
        let messages = "\(count) \(count == 1 ? "message" : "messages")"
        guard let date = Self.parseDate(conversation.updatedAt) else {
            return messages
        }
        return "\(messages) - \(date.formatted(.relative(presentation: .named)))"
    }

    private static func parseDate(_ value: String) -> Date? {
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if let date = fractional.date(from: value) {
            return date
        }
        return ISO8601DateFormatter().date(from: value)
    }
}
