import SwiftUI

struct ApprovalCard: View {
    let action: PendingAction
    let isDisabled: Bool
    let onDecision: (Bool) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(spacing: 8) {
                Circle()
                    .fill(DjinTheme.risk(action.risk))
                    .frame(width: 9, height: 9)
                    .accessibilityHidden(true)
                Text(action.toolName)
                    .font(.headline)
                Spacer(minLength: 8)
                Text(action.risk.uppercased())
                    .font(.caption.weight(.bold))
                    .foregroundStyle(DjinTheme.risk(action.risk))
            }

            Text(action.preview)
                .font(.callout.monospaced())
                .foregroundStyle(DjinTheme.secondaryText)
                .textSelection(.enabled)

            ViewThatFits(in: .horizontal) {
                HStack(spacing: 12) { decisionButtons }
                VStack(spacing: 10) { decisionButtons }
            }
        }
        .padding(16)
        .background(DjinTheme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(DjinTheme.risk(action.risk), lineWidth: 1)
        }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private var decisionButtons: some View {
        Button {
            onDecision(false)
        } label: {
            Label("Reject", systemImage: "xmark")
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.bordered)
        .tint(DjinTheme.danger)
        .disabled(isDisabled)

        Button {
            onDecision(true)
        } label: {
            Label("Approve", systemImage: "checkmark")
                .frame(maxWidth: .infinity, minHeight: 44)
        }
        .buttonStyle(.borderedProminent)
        .tint(DjinTheme.accent)
        .foregroundStyle(DjinTheme.accentInk)
        .disabled(isDisabled)
    }
}
