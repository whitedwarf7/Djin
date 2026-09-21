import unittest

from djin import agent


class AgentEventContractTests(unittest.TestCase):
    def test_session_title_removes_request_filler(self) -> None:
        title = agent._title_from(
            "Hello, could you please summarize my unread emails from last week?"
        )

        self.assertEqual(title, "Summarize my unread emails from last week")

    def test_session_title_skips_a_standalone_greeting(self) -> None:
        title = agent._title_from("Hi! Please review tomorrow's calendar and flag conflicts.")

        self.assertEqual(title, "Review tomorrow's calendar and flag conflicts")

    def test_session_title_is_bounded_and_word_safe(self) -> None:
        title = agent._title_from(
            "Compare the quarterly revenue reports for Germany and France and highlight every important difference"
        )

        self.assertEqual(title, "Compare the quarterly revenue reports for Germany…")
        self.assertLessEqual(len(title), 53)

    def test_empty_session_title_has_a_useful_fallback(self) -> None:
        self.assertEqual(agent._title_from("  \n  "), "New conversation")

    def test_running_tool_event_includes_call_identifier(self) -> None:
        event = agent._running_event(
            {"id": "call-123", "function": {"name": "missing_test_tool"}}
        )

        self.assertEqual(event["type"], "tool")
        self.assertEqual(event["tool_call_id"], "call-123")
        self.assertEqual(event["status"], "running")

    def test_missing_tool_call_identifier_is_added_before_persistence(self) -> None:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [{"function": {"name": "missing_test_tool", "arguments": "{}"}}],
        }

        calls = agent._tool_calls_with_ids(message)

        self.assertTrue(calls[0]["id"])
        self.assertEqual(message["tool_calls"][0]["id"], calls[0]["id"])

    def test_persisted_tool_status_is_not_sent_to_model(self) -> None:
        stored = agent._tool_message(
            "call-123", "missing_test_tool", "Tool error: unavailable", status="error"
        )

        self.assertEqual(stored["_status"], "error")
        api_message = agent._api_messages([stored])[1]
        self.assertNotIn("_status", api_message)
        self.assertEqual(api_message["content"], "Tool error: unavailable")


if __name__ == "__main__":
    unittest.main()