import XCTest
@testable import Djin

final class SSEDecoderTests: XCTestCase {
    func testDecodesDeltaEvent() throws {
        let event = try XCTUnwrap(
            SSEDecoder().decode(line: "data: {\"type\":\"delta\",\"content\":\"Hello\"}")
        )

        XCTAssertEqual(event.type, "delta")
        XCTAssertEqual(event.content, "Hello")
    }

    func testIgnoresCommentsAndBlankLines() throws {
        XCTAssertNil(try SSEDecoder().decode(line: ": keep-alive"))
        XCTAssertNil(try SSEDecoder().decode(line: ""))
    }

    func testDecodesToolCallIdentifier() throws {
        let line = #"data: {"type":"tool","tool_call_id":"t1","tool":"gmail_search","risk":"read","status":"ok"}"#
        let event = try XCTUnwrap(SSEDecoder().decode(line: line))

        XCTAssertEqual(event.toolCallID, "t1")
        XCTAssertEqual(event.status, "ok")
    }

    func testDecodesPendingAction() throws {
        let line = #"data: {"type":"pending","actions":[{"id":"a1","conversation_id":"c1","tool_call_id":"t1","tool_name":"calendar_create_event","risk":"external","preview":"Create an event","status":"pending","created_at":"2026-09-21T10:00:00+00:00"}]}"#
        let event = try XCTUnwrap(SSEDecoder().decode(line: line))

        XCTAssertEqual(event.actions?.first?.toolName, "calendar_create_event")
        XCTAssertEqual(event.actions?.first?.risk, "external")
    }
}
