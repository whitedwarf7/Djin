import XCTest
@testable import Djin

final class APIModelsTests: XCTestCase {
    func testDecodesStoredConversationAndToolResult() throws {
        let json = #"{"conversation_id":"c1","messages":[{"role":"assistant","content":"Checking.","tool_calls":[{"id":"t1","function":{"name":"gmail_search","arguments":"{}"}}]},{"role":"tool","tool_call_id":"t1","name":"gmail_search","content":"Found 2 messages","_status":"ok"}],"pending":[]}"#
        let detail = try JSONDecoder().decode(
            ConversationDetail.self,
            from: try XCTUnwrap(json.data(using: .utf8))
        )

        XCTAssertEqual(detail.conversationID, "c1")
        XCTAssertEqual(detail.messages.first?.toolCalls?.first?.function.name, "gmail_search")
        XCTAssertEqual(detail.messages.last?.toolCallID, "t1")
        XCTAssertEqual(detail.messages.last?.toolStatus, "ok")
    }

    func testDecodesServerStatus() throws {
        let json = #"{"provider":"openai","model":"gpt-test","llm_key_present":true,"auto_approve_write":false,"integrations":{"google":{"configured":true,"connected":true},"search":{"configured":false,"provider":"none"},"notes":{"configured":true,"path":"data/notes"},"scheduler":{"configured":true,"connected":true,"count":1,"enabled_count":1},"notifications":{"configured":false,"provider":"ntfy"}},"tools":[{"name":"notes_list","risk":"read","description":"List notes"}],"voice":{}}"#
        let status = try JSONDecoder().decode(
            ServerStatus.self,
            from: try XCTUnwrap(json.data(using: .utf8))
        )

        XCTAssertTrue(status.llmKeyPresent)
        XCTAssertEqual(status.integrations.scheduler.enabledCount, 1)
        XCTAssertEqual(status.tools.first?.risk, "read")
    }
}