import SwiftUI

struct ChatView: View {
    @ObservedObject var model: ChatViewModel
    let user: UserProfile
    let onSignOut: () -> Void

    @State private var draft = ""
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if let bannerMessage = model.bannerMessage {
                    ErrorBanner(message: bannerMessage) {
                        model.bannerMessage = nil
                    }
                }
                transcript
                ComposerView(
                    text: $draft,
                    isDisabled: model.isBusy || !model.pendingActions.isEmpty,
                    onSend: sendDraft
                )
            }
            .background(DjinTheme.background)
            .foregroundStyle(DjinTheme.primaryText)
            .navigationTitle("Djin")
            .toolbar { toolbarContent }
            .overlay {
                if model.isLoadingConversation {
                    ZStack {
                        DjinTheme.background.opacity(0.82)
                        ProgressView("Opening session")
                    }
                }
            }
        }
    }

    private var transcript: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 18) {
                    if model.timeline.isEmpty,
                       model.pendingActions.isEmpty,
                       !model.isBusy {
                        ChatEmptyState(suggestions: model.suggestions) { suggestion in
                            draft = suggestion
                        }
                    }

                    ForEach(model.timeline) { item in
                        TimelineItemView(item: item)
                    }

                    ForEach(model.pendingActions) { action in
                        ApprovalCard(action: action, isDisabled: model.isBusy) { approved in
                            Task {
                                await model.decide(action, approve: approved)
                            }
                        }
                    }

                    if model.showsThinking {
                        ThinkingRow()
                    }

                    Color.clear
                        .frame(height: 1)
                        .id("transcript-bottom")
                }
                .frame(maxWidth: 720)
                .padding(.horizontal, 16)
                .padding(.vertical, 20)
                .frame(maxWidth: .infinity)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: model.timeline) { _, _ in
                scrollToBottom(proxy)
            }
            .onChange(of: model.pendingActions) { _, _ in
                scrollToBottom(proxy)
            }
            .onChange(of: model.isBusy) { _, _ in
                scrollToBottom(proxy)
            }
        }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Label(
                model.statusText,
                systemImage: model.isReady ? "checkmark.circle.fill" : "exclamationmark.circle.fill"
            )
            .font(.caption.weight(.semibold))
            .foregroundStyle(model.isReady ? DjinTheme.success : DjinTheme.danger)
            .accessibilityLabel("Server status: \(model.statusText)")
        }

        ToolbarItemGroup(placement: .topBarTrailing) {
            Button {
                model.startNewConversation()
                draft = ""
            } label: {
                Image(systemName: "square.and.pencil")
            }
            .disabled(model.isBusy)
            .accessibilityLabel("New conversation")

            Menu {
                Section("\(user.username) - \(user.role)") {
                    Button(role: .destructive, action: onSignOut) {
                        Label("Sign out", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            } label: {
                Image(systemName: "person.crop.circle")
            }
            .accessibilityLabel("Account")
        }
    }

    private func sendDraft() {
        let message = draft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty else {
            return
        }
        draft = ""
        Task {
            await model.send(message)
        }
    }

    private func scrollToBottom(_ proxy: ScrollViewProxy) {
        withAnimation(reduceMotion ? nil : .easeOut(duration: 0.2)) {
            proxy.scrollTo("transcript-bottom", anchor: .bottom)
        }
    }
}

private struct ChatEmptyState: View {
    let suggestions: [String]
    let onSelect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .frame(width: 56, height: 56)
                .accessibilityHidden(true)

            Text("What should I dig into?")
                .font(.title2.bold())

            VStack(spacing: 10) {
                ForEach(suggestions, id: \.self) { suggestion in
                    Button {
                        onSelect(suggestion)
                    } label: {
                        HStack(spacing: 12) {
                            Text(suggestion)
                                .multilineTextAlignment(.leading)
                            Spacer(minLength: 8)
                            Image(systemName: "arrow.up.right")
                                .accessibilityHidden(true)
                        }
                        .font(.body)
                        .foregroundStyle(DjinTheme.primaryText)
                        .padding(.horizontal, 14)
                        .frame(maxWidth: .infinity, minHeight: 50, alignment: .leading)
                        .background(DjinTheme.surface, in: RoundedRectangle(cornerRadius: 8))
                        .overlay {
                            RoundedRectangle(cornerRadius: 8)
                                .stroke(DjinTheme.divider, lineWidth: 1)
                        }
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(.top, 36)
    }
}

private struct ErrorBanner: View {
    let message: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            Image(systemName: "exclamationmark.circle.fill")
                .accessibilityHidden(true)
            Text(message)
                .font(.callout)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button(action: onDismiss) {
                Image(systemName: "xmark")
                    .frame(width: 44, height: 44)
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss error")
        }
        .foregroundStyle(DjinTheme.danger)
        .padding(.leading, 16)
        .padding(.trailing, 6)
        .background(DjinTheme.danger.opacity(0.1))
        .accessibilityElement(children: .combine)
    }
}

private struct ThinkingRow: View {
    var body: some View {
        HStack(spacing: 10) {
            ProgressView()
                .controlSize(.small)
            Text("Thinking")
                .font(.callout)
                .foregroundStyle(DjinTheme.secondaryText)
        }
        .frame(minHeight: 44)
        .accessibilityElement(children: .combine)
    }
}
