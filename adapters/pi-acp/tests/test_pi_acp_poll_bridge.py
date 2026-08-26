import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pi_acp_poll_bridge as poll_bridge


class PiAcpPollBridgeTests(unittest.TestCase):
    def test_poll_once_attempts_all_channels_in_order(self):
        calls = []

        def fetch(channel_id, limit):
            calls.append((channel_id, limit))
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            poll_bridge.poll_channels_once(
                ["chan-a", "chan-b"],
                17,
                "agent-pubkey",
                ["pi-chat"],
                set(),
                0,
                set(),
                object(),
                Path(temp_dir) / "seen.json",
                fetch_messages=fetch,
            )

        self.assertEqual(calls, [("chan-a", 17), ("chan-b", 17)])

    def test_poll_once_continues_after_channel_fetch_failure(self):
        calls = []

        def fetch(channel_id, limit):
            calls.append(channel_id)
            if channel_id == "chan-a":
                raise RuntimeError("channel unavailable")
            return []

        with tempfile.TemporaryDirectory() as temp_dir:
            poll_bridge.poll_channels_once(
                ["chan-a", "chan-b"],
                30,
                "agent-pubkey",
                ["pi-chat"],
                set(),
                0,
                set(),
                object(),
                Path(temp_dir) / "seen.json",
                fetch_messages=fetch,
            )

        self.assertEqual(calls, ["chan-a", "chan-b"])

    def test_poll_once_prompt_includes_source_channel_id(self):
        class FakeAcp:
            def __init__(self):
                self.prompts = []

            def prompt(self, prompt_text):
                self.prompts.append(prompt_text)

        acp = FakeAcp()

        def fetch(channel_id, limit):
            return [{
                "id": channel_id * 64,
                "content": "@pi-chat help",
                "pubkey": "author-pubkey",
                "created_at": 100,
            }]

        with tempfile.TemporaryDirectory() as temp_dir:
            poll_bridge.poll_channels_once(
                ["chan-a", "chan-b"],
                30,
                "agent-pubkey",
                ["pi-chat"],
                set(),
                0,
                set(),
                acp,
                Path(temp_dir) / "seen.json",
                fetch_messages=fetch,
            )

        self.assertEqual(len(acp.prompts), 2)
        self.assertIn("#chan-a", acp.prompts[0])
        self.assertIn("#chan-b", acp.prompts[1])

    def test_resolve_channel_ids_prefers_multi_channel_environment(self):
        self.assertEqual(
            poll_bridge.resolve_channel_ids({
                "PI_CHAT_CHANNELS": "chan-a, chan-b",
                "PI_CHAT_CHANNEL_ID": "legacy",
            }),
            ["chan-a", "chan-b"],
        )

    def test_resolve_channel_ids_falls_back_to_legacy_environment(self):
        self.assertEqual(
            poll_bridge.resolve_channel_ids({"PI_CHAT_CHANNEL_ID": "legacy"}),
            ["legacy"],
        )

    def test_resolve_channel_ids_rejects_empty_configuration(self):
        with self.assertRaisesRegex(RuntimeError, "PI_CHAT_CHANNELS or PI_CHAT_CHANNEL_ID is required"):
            poll_bridge.resolve_channel_ids({})

    def test_parse_channel_ids_trims_deduplicates_and_preserves_order(self):
        self.assertEqual(
            poll_bridge.parse_channel_ids("chan-a, chan-b,chan-a"),
            ["chan-a", "chan-b"],
        )

    def test_prompt_uses_the_channel_that_produced_the_event(self):
        prompt = poll_bridge.prompt_for_event(
            {"id": "a" * 64, "content": "@pi-chat help", "pubkey": "b" * 64},
            "11111111-2222-3333-4444-555555555555",
            "AI Engineering Lab",
        )
        self.assertIn("#11111111-2222-3333-4444-555555555555", prompt)

    def test_event_matches_pubkey_mention_tag(self):
        event = {"tags": [["p", "agent-pubkey"]], "content": "hello"}

        self.assertTrue(poll_bridge.event_mentions_agent(event, "agent-pubkey", ["pi-chat"]))

    def test_event_matches_textual_pi_chat_prefix_without_mention_tag(self):
        event = {"tags": [], "content": "pi-chat, tell me the difference between you and hermes"}

        self.assertTrue(poll_bridge.event_mentions_agent(event, "agent-pubkey", ["pi-chat"]))

    def test_event_does_not_match_different_textual_agent_prefix(self):
        event = {"tags": [], "content": "pi-learning, tell me the difference between you and hermes"}

        self.assertFalse(poll_bridge.event_mentions_agent(event, "agent-pubkey", ["pi-chat"]))


if __name__ == "__main__":
    unittest.main()
