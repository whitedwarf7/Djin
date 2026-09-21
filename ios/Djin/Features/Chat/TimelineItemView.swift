import SwiftUI

struct TimelineItemView: View {
    let item: TimelineItem

    @ViewBuilder
    var body: some View {
        switch item.kind {
        case .user:
            userMessage
        case .assistant:
            assistantMessage
        case .tool:
            toolActivity
        case .error:
            errorMessage
        }
    }

    private var userMessage: some View {
        HStack(alignment: .top) {
            Spacer(minLength: 52)
            Text(item.content)
                .font(.body)
                .foregroundStyle(DjinTheme.primaryText)
                .textSelection(.enabled)
                .padding(.horizontal, 14)
                .padding(.vertical, 11)
                .background(DjinTheme.raisedSurface, in: RoundedRectangle(cornerRadius: 8))
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("You: \(item.content)")
    }

    private var assistantMessage: some View {
        HStack(alignment: .top, spacing: 10) {
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .frame(width: 28, height: 28)
                .accessibilityHidden(true)

            MarkdownText(content: item.content)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Djin: \(item.content)")
    }

    private var toolActivity: some View {
        let name = item.toolName ?? "Tool"
        let state = readableStatus(item.status)
        let risk = item.risk ?? "read"

        return HStack(spacing: 10) {
            Circle()
                .fill(DjinTheme.risk(risk))
                .frame(width: 8, height: 8)
                .accessibilityHidden(true)
            Text(name)
                .font(.callout.weight(.semibold))
                .lineLimit(1)
            Spacer(minLength: 8)
            Text("\(risk) - \(state)")
                .font(.caption)
                .foregroundStyle(DjinTheme.secondaryText)
                .multilineTextAlignment(.trailing)
        }
        .padding(.horizontal, 12)
        .frame(minHeight: 44)
        .background(DjinTheme.surface, in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(DjinTheme.divider, lineWidth: 1)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(name), \(risk) risk, \(state)")
    }

    private var errorMessage: some View {
        Label(item.content, systemImage: "exclamationmark.triangle.fill")
            .font(.callout)
            .foregroundStyle(DjinTheme.danger)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(12)
            .background(DjinTheme.danger.opacity(0.1), in: RoundedRectangle(cornerRadius: 8))
            .accessibilityLabel("Error: \(item.content)")
    }

    private func readableStatus(_ value: String?) -> String {
        switch value {
        case "running":
            return "running"
        case "ok":
            return "done"
        case "error":
            return "failed"
        case "pending":
            return "awaiting approval"
        case "skipped":
            return "declined"
        case "blocked":
            return "blocked"
        case "unknown":
            return "not completed"
        default:
            return value ?? "unknown"
        }
    }
}

private struct MarkdownText: View {
    let content: String

    var body: some View {
        Text(attributedContent)
            .font(.body)
            .foregroundStyle(DjinTheme.primaryText)
            .textSelection(.enabled)
    }

    private var attributedContent: AttributedString {
        (try? AttributedString(
            markdown: content,
            options: .init(interpretedSyntax: .full)
        )) ?? AttributedString(content)
    }
}
