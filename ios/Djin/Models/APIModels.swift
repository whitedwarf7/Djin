import Foundation

struct UserProfile: Codable, Equatable, Sendable {
    let id: String
    let username: String
    let role: String
}

struct AuthResponse: Decodable, Equatable, Sendable {
    let accessToken: String
    let tokenType: String
    let expiresIn: Int
    let user: UserProfile

    enum CodingKeys: String, CodingKey {
        case accessToken = "access_token"
        case tokenType = "token_type"
        case expiresIn = "expires_in"
        case user
    }
}

struct LoginRequest: Encodable, Sendable {
    let username: String
    let password: String
}

struct ServerStatus: Decodable, Equatable, Sendable {
    let provider: String
    let model: String
    let llmKeyPresent: Bool
    let autoApproveWrite: Bool
    let integrations: StatusIntegrations
    let tools: [ToolDescriptor]

    enum CodingKeys: String, CodingKey {
        case provider
        case model
        case llmKeyPresent = "llm_key_present"
        case autoApproveWrite = "auto_approve_write"
        case integrations
        case tools
    }
}

struct StatusIntegrations: Decodable, Equatable, Sendable {
    let google: IntegrationStatus
    let search: IntegrationStatus
    let notes: IntegrationStatus
    let scheduler: IntegrationStatus
    let notifications: IntegrationStatus
}

struct IntegrationStatus: Decodable, Equatable, Sendable {
    let configured: Bool?
    let connected: Bool?
    let provider: String?
    let path: String?
    let count: Int?
    let enabledCount: Int?

    enum CodingKeys: String, CodingKey {
        case configured
        case connected
        case provider
        case path
        case count
        case enabledCount = "enabled_count"
    }
}

struct ToolDescriptor: Decodable, Equatable, Sendable {
    let name: String
    let risk: String
    let description: String
}

struct ConversationSummary: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let title: String
    let createdAt: String
    let updatedAt: String
    let messageCount: Int

    enum CodingKeys: String, CodingKey {
        case id
        case title
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case messageCount = "message_count"
    }
}

struct ConversationDetail: Decodable, Equatable, Sendable {
    let conversationID: String
    let messages: [StoredMessage]
    let pending: [PendingAction]

    enum CodingKeys: String, CodingKey {
        case conversationID = "conversation_id"
        case messages
        case pending
    }
}

struct StoredMessage: Decodable, Equatable, Sendable {
    let role: String
    let content: String?
    let toolCallID: String?
    let name: String?
    let toolStatus: String?
    let toolCalls: [StoredToolCall]?

    enum CodingKeys: String, CodingKey {
        case role
        case content
        case toolCallID = "tool_call_id"
        case name
        case toolStatus = "_status"
        case toolCalls = "tool_calls"
    }
}

struct StoredToolCall: Decodable, Equatable, Sendable {
    let id: String?
    let function: StoredToolFunction
}

struct StoredToolFunction: Decodable, Equatable, Sendable {
    let name: String
}

struct PendingAction: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let conversationID: String
    let toolCallID: String
    let toolName: String
    let risk: String
    let preview: String
    let status: String
    let createdAt: String

    enum CodingKeys: String, CodingKey {
        case id
        case conversationID = "conversation_id"
        case toolCallID = "tool_call_id"
        case toolName = "tool_name"
        case risk
        case preview
        case status
        case createdAt = "created_at"
    }
}

struct ChatRequest: Encodable, Sendable {
    let message: String
    let conversationID: String?
    let voice: Bool

    enum CodingKeys: String, CodingKey {
        case message
        case conversationID = "conversation_id"
        case voice
    }
}

struct DecisionRequest: Encodable, Sendable {
    let approve: Bool
    let voice: Bool
}

struct StreamEvent: Decodable, Equatable, Sendable {
    let type: String
    let conversationID: String?
    let toolCallID: String?
    let content: String?
    let tool: String?
    let risk: String?
    let status: String?
    let approval: String?
    let summary: String?
    let actions: [PendingAction]?
    let message: String?

    enum CodingKeys: String, CodingKey {
        case type
        case conversationID = "conversation_id"
        case toolCallID = "tool_call_id"
        case content
        case tool
        case risk
        case status
        case approval
        case summary
        case actions
        case message
    }
}

struct DeleteResponse: Decodable, Equatable, Sendable {
    let deleted: Bool
}
