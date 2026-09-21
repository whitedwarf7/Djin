import SwiftUI

struct ComposerView: View {
    @Binding var text: String
    let isDisabled: Bool
    let onSend: () -> Void

    @FocusState private var isFocused: Bool

    private var canSend: Bool {
        !isDisabled && !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        HStack(alignment: .bottom, spacing: 10) {
            TextField(
                isDisabled ? "Resolve the approval to continue" : "Message Djin",
                text: $text,
                axis: .vertical
            )
            .lineLimit(1...5)
            .focused($isFocused)
            .submitLabel(.send)
            .onSubmit {
                if canSend {
                    onSend()
                }
            }
            .disabled(isDisabled)
            .djinField(focused: isFocused)

            Button(action: onSend) {
                Image(systemName: "arrow.up")
                    .font(.headline)
                    .foregroundStyle(DjinTheme.accentInk)
                    .frame(width: 48, height: 48)
                    .background(DjinTheme.accent, in: Circle())
                    .contentShape(Circle())
            }
            .buttonStyle(.plain)
            .disabled(!canSend)
            .opacity(canSend ? 1 : 0.38)
            .accessibilityLabel("Send message")
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .background(DjinTheme.background)
        .overlay(alignment: .top) {
            Rectangle()
                .fill(DjinTheme.divider)
                .frame(height: 1)
        }
    }
}
