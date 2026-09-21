import Foundation

struct TimelineItem: Identifiable, Equatable, Sendable {
    enum Kind: Equatable, Sendable {
        case user
        case assistant
        case tool
        case error
    }

    let id: UUID
    let kind: Kind
    var content: String
    var toolName: String?
    var risk: String?
    var status: String?
    var toolCallID: String?

    init(
        id: UUID = UUID(),
        kind: Kind,
        content: String,
        toolName: String? = nil,
        risk: String? = nil,
        status: String? = nil,
        toolCallID: String? = nil
    ) {
        self.id = id
        self.kind = kind
        self.content = content
        self.toolName = toolName
        self.risk = risk
        self.status = status
        self.toolCallID = toolCallID
    }
}
