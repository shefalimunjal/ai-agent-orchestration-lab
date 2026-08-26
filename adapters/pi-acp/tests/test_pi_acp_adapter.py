import io
import json
import os
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pi_acp_adapter as adapter


class PiAcpAdapterTests(unittest.TestCase):
    def test_build_pi_prompt_includes_runtime_configuration(self):
        original_env = {
            key: os.environ.get(key)
            for key in (
                "PI_ACP_PROVIDER",
                "PI_ACP_MODEL",
                "PI_ACP_THINKING",
                "PI_ACP_TOOLS",
                "PI_ACP_TRANSPORT_DESCRIPTION",
            )
        }
        os.environ["PI_ACP_PROVIDER"] = "openai-codex"
        os.environ["PI_ACP_MODEL"] = "gpt-5.5"
        os.environ["PI_ACP_THINKING"] = "low"
        os.environ["PI_ACP_TOOLS"] = "read,grep,find,ls"
        os.environ["PI_ACP_TRANSPORT_DESCRIPTION"] = (
            "Buzz -> pi-chat ACP poll bridge -> pi-acp -> Pi RPC"
        )

        try:
            prompt = adapter.build_pi_prompt("hello")
        finally:
            for key, value in original_env.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertIn("provider: openai-codex", prompt)
        self.assertIn("model: gpt-5.5", prompt)
        self.assertIn("thinking/reasoning: low", prompt)
        self.assertIn("allowed tools: read,grep,find,ls", prompt)
        self.assertIn("Buzz -> pi-chat ACP poll bridge -> pi-acp -> Pi RPC", prompt)
        self.assertIn("hello", prompt)

    def test_initialize_response_advertises_acp_v2_without_auth_methods(self):
        response = adapter.handle_initialize({"id": 7, "params": {"protocolVersion": 2}})

        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertEqual(response["id"], 7)
        self.assertEqual(response["result"]["protocolVersion"], 2)
        self.assertEqual(response["result"]["agentCapabilities"], {})
        self.assertEqual(response["result"]["authMethods"], [])

    def test_prompt_blocks_are_joined_in_order(self):
        prompt = adapter.extract_prompt_text(
            {
                "prompt": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                    {"type": "image", "data": "ignored"},
                ]
            }
        )

        self.assertEqual(prompt, "first\n\nsecond")

    def test_routing_is_extracted_from_buzz_prompt_context(self):
        prompt = """[Context]
Scope: channel
Channel: 74c3e47d-2437-4014-8496-995ee5dd1a2c

[Buzz event: @mention]
Event ID: 5d0956166125ca04b69264d21a882109bf7ffa1e3497e7bd3a6df61835f10fa7
Content: pi-chat hello
IMPORTANT: This is a new top-level message. For ordinary replies in this turn, use `--reply-to 5d0956166125ca04b69264d21a882109bf7ffa1e3497e7bd3a6df61835f10fa7` on `buzz messages send`.
"""

        routing = adapter.extract_buzz_routing(prompt)

        self.assertEqual(routing.channel_id, "74c3e47d-2437-4014-8496-995ee5dd1a2c")
        self.assertEqual(
            routing.reply_to,
            "5d0956166125ca04b69264d21a882109bf7ffa1e3497e7bd3a6df61835f10fa7",
        )

    def test_routing_is_extracted_from_buzz_prompt_channel_display_name(self):
        prompt = """[Context]
Scope: channel
Channel: Pi Chat (#45ecf33f-e4fc-430b-a504-2d929bf51ee4)

[Buzz event: @mention]
Event ID: 507f0ce6770f456f739e5cd781b53002b87b84484a4f9294cdced4fd22c2c21a
Content: pi-chat hello
"""

        routing = adapter.extract_buzz_routing(prompt)

        self.assertEqual(routing.channel_id, "45ecf33f-e4fc-430b-a504-2d929bf51ee4")
        self.assertEqual(
            routing.reply_to,
            "507f0ce6770f456f739e5cd781b53002b87b84484a4f9294cdced4fd22c2c21a",
        )

    def test_collect_pi_answer_uses_text_deltas_until_agent_end(self):
        lines = [
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "hello "},
                }
            ),
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "world"},
                }
            ),
            json.dumps({"type": "agent_end"}),
        ]

        answer = adapter.collect_pi_answer(iter(lines), session_id="sess-1", emit_update=lambda _: None)

        self.assertEqual(answer, "hello world")

    def test_collect_pi_answer_ignores_nonblocking_extension_ui_status_updates(self):
        lines = [
            json.dumps(
                {
                    "type": "extension_ui_request",
                    "id": "status-1",
                    "method": "setStatus",
                    "statusKey": "mcp",
                }
            ),
            json.dumps(
                {
                    "type": "message_update",
                    "assistantMessageEvent": {"type": "text_delta", "delta": "still working"},
                }
            ),
            json.dumps({"type": "agent_end"}),
        ]

        answer = adapter.collect_pi_answer(iter(lines), session_id="sess-1", emit_update=lambda _: None)

        self.assertEqual(answer, "still working")

    def test_collect_pi_answer_raises_on_extension_ui_request(self):
        lines = [
            json.dumps(
                {
                    "type": "extension_ui_request",
                    "id": "ask-1",
                    "request": {"type": "confirm", "message": "Allow?"},
                }
            )
        ]

        with self.assertRaisesRegex(RuntimeError, "interactive Pi request"):
            adapter.collect_pi_answer(iter(lines), session_id="sess-1", emit_update=lambda _: None)


if __name__ == "__main__":
    unittest.main()
