import unittest

from djin import agent


class AgentEventContractTests(unittest.TestCase):
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