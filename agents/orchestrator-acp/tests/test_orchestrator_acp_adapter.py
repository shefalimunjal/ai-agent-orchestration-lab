import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import orchestrator_acp_adapter as adapter
import orchestrator_entrypoint as entrypoint
from orchestrator_core import Delegation, Worker


class OrchestratorAdapterTests(unittest.TestCase):
    def test_initialize_advertises_orchestrator_acp(self):
        response = adapter.handle_initialize({"id": 7, "params": {"protocolVersion": 2}})
        self.assertEqual(response["result"]["protocolVersion"], 2)
        self.assertEqual(response["result"]["agentInfo"]["name"], "orchestrator-acp")

    def test_extracts_channel_event_and_human_content(self):
        prompt = """[Context]
Scope: channel
Channel: AI Engineering Lab (#11111111-2222-3333-4444-555555555555)

[Buzz event: @mention]
Event ID: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Content: @orchestrator-chat ask all three agents to explain ACP
IMPORTANT: This is a new top-level message.
"""
        routing = adapter.extract_buzz_routing(prompt)
        self.assertEqual(routing.channel_id, "11111111-2222-3333-4444-555555555555")
        self.assertEqual(routing.reply_to, "a" * 64)
        self.assertEqual(
            adapter.extract_human_task(prompt),
            "ask all three agents to explain ACP",
        )

    def test_parse_send_response_requires_event_id(self):
        self.assertEqual(adapter.parse_send_event_id('{"event_id":"' + "d" * 64 + '"}'), "d" * 64)
        with self.assertRaisesRegex(RuntimeError, "event_id"):
            adapter.parse_send_event_id('{"ok":true}')

    def test_collection_stops_when_all_delegations_reply(self):
        hermes = Worker("hermes", "hermes-learning", "a" * 64, "architecture", ())
        pi = Worker("pi", "pi-chat", "b" * 64, "workflow", ())
        delegations = [Delegation(hermes, "d" * 64), Delegation(pi, "e" * 64)]

        class FakeBuzz:
            def get(self, channel_id, limit=100, timeout=None):
                self.channel_id = channel_id
                return [
                    {"id": "1" * 64, "pubkey": "a" * 64, "created_at": 101, "content": "Hermes answer", "tags": [["e", "d" * 64, "", "reply"]]},
                    {"id": "2" * 64, "pubkey": "b" * 64, "created_at": 102, "content": "Pi answer", "tags": [["e", "e" * 64, "", "reply"]]},
                ]

        contributions, timed_out = adapter.collect_contributions(
            FakeBuzz(),
            "11111111-2222-3333-4444-555555555555",
            delegations,
            not_before=100,
            timeout_secs=90,
            poll_secs=3,
            clock=lambda: 0.0,
            sleeper=lambda seconds: None,
        )
        self.assertEqual([item.worker_slug for item in contributions], ["hermes", "pi"])
        self.assertEqual(timed_out, [])

    def test_collection_returns_timeout_names_at_deadline(self):
        hermes = Worker("hermes", "hermes-learning", "a" * 64, "architecture", ())
        times = iter((0.0, 91.0))

        class FakeBuzz:
            def get(self, channel_id, limit=100, timeout=None):
                return []

        contributions, timed_out = adapter.collect_contributions(
            FakeBuzz(),
            "11111111-2222-3333-4444-555555555555",
            [Delegation(hermes, "d" * 64)],
            not_before=100,
            timeout_secs=90,
            poll_secs=3,
            clock=lambda: next(times),
            sleeper=lambda seconds: None,
        )
        self.assertEqual(contributions, [])
        self.assertEqual(timed_out, ["hermes"])

    def test_collection_treats_runtime_read_failure_as_failed_poll(self):
        hermes = Worker("hermes", "hermes-learning", "a" * 64, "architecture", ())
        times = iter((0.0, 0.0, 0.0, 10.0))
        sleeps = []

        class FailingBuzz:
            def get(self, channel_id, limit=100, timeout=None):
                raise RuntimeError("buzz messages get failed")

        try:
            contributions, timed_out = adapter.collect_contributions(
                FailingBuzz(),
                "channel",
                [Delegation(hermes, "d" * 64)],
                not_before=100,
                timeout_secs=10,
                poll_secs=1,
                clock=lambda: next(times),
                sleeper=sleeps.append,
            )
        except RuntimeError as exc:
            self.fail(f"sanitized Buzz read failure escaped collection: {exc}")

        self.assertEqual(contributions, [])
        self.assertEqual(timed_out, ["hermes"])
        self.assertEqual(sleeps, [1])

    def test_entrypoint_rejects_identity_without_private_key(self):
        with self.assertRaisesRegex(RuntimeError, "private key"):
            entrypoint.load_private_key({"public_key_hex": "a" * 64})

    def test_buzz_send_uses_narrow_environment_and_required_command(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return type("Completed", (), {"returncode": 0, "stdout": '{"event_id":"' + "d" * 64 + '"}', "stderr": ""})()

        client = adapter.BuzzClient(
            subprocess_run=fake_run,
            environ={
                "BUZZ_PRIVATE_KEY": "test-private-key",
                "BUZZ_RELAY_URL": "ws://relay.test:3000",
                "ORCHESTRATOR_IDENTITY_FILE": "/not/an/identity",
                "CODEX_HOME": "/not/for/buzz",
                "PATH": "/usr/bin",
            },
        )
        event_id = client.send("channel", "message", reply_to="a" * 64, mention="b" * 64)

        self.assertEqual(event_id, "d" * 64)
        command, kwargs = calls[0]
        self.assertEqual(
            command,
            ["/buzz-bin/buzz", "messages", "send", "--channel", "channel", "--content", "-", "--reply-to", "a" * 64, "--mention", "b" * 64],
        )
        self.assertEqual(kwargs["input"], "message")
        self.assertEqual(kwargs["env"]["BUZZ_RELAY_URL"], "http://relay.test:3000")
        self.assertIn("BUZZ_PRIVATE_KEY", kwargs["env"])
        self.assertNotIn("ORCHESTRATOR_IDENTITY_FILE", kwargs["env"])
        self.assertNotIn("CODEX_HOME", kwargs["env"])

    def test_buzz_send_uses_configured_subprocess_timeout(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return type("Completed", (), {
                "returncode": 0,
                "stdout": '{"event_id":"' + "d" * 64 + '"}',
                "stderr": "",
            })()

        client = adapter.BuzzClient(
            subprocess_run=fake_run,
            environ={
                "BUZZ_PRIVATE_KEY": "test-private-key",
                "ORCHESTRATOR_BUZZ_TIMEOUT_SECS": "1.25",
            },
        )
        client.send("channel", "message")

        self.assertEqual(calls[0][1].get("timeout"), 1.25)

    def test_buzz_get_uses_requested_subprocess_timeout(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return type("Completed", (), {"returncode": 0, "stdout": "[]", "stderr": ""})()

        client = adapter.BuzzClient(
            subprocess_run=fake_run,
            environ={"BUZZ_PRIVATE_KEY": "test-private-key", "PATH": "/usr/bin"},
        )
        self.assertEqual(client.get("channel", timeout=1.25), [])
        self.assertEqual(calls[0][0], ["/buzz-bin/buzz", "messages", "get", "--channel", "channel", "--limit", "100"])
        self.assertEqual(calls[0][1]["timeout"], 1.25)

    def test_orchestrate_uses_configured_buzz_cli(self):
        configured = "/Applications/BuzzLab/bin/buzz"
        client = mock.Mock()
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_BUZZ_CLI": configured}), mock.patch.object(
            adapter, "BuzzClient", return_value=client
        ) as client_type, mock.patch.object(adapter, "load_workers_from_env", return_value=[]), mock.patch.object(
            adapter, "collect_contributions", return_value=([], [])
        ):
            client.send.return_value = "d" * 64
            adapter.orchestrate(
                "Channel: AI Engineering Lab (#11111111-2222-3333-4444-555555555555)\n"
                "Event ID: " + "a" * 64 + "\nContent: @orchestrator-chat health check",
                "session",
            )

        client_type.assert_called_once_with(buzz_cli=configured)

    def test_collection_checks_deadline_before_fetch_and_caps_sleep(self):
        hermes = Worker("hermes", "hermes-learning", "a" * 64, "architecture", ())
        calls = []
        sleeps = []
        times = iter((0.0, 0.0, 9.5, 10.0))

        class FakeBuzz:
            def get(self, channel_id, limit=100, timeout=None):
                calls.append(timeout)
                return []

        contributions, timed_out = adapter.collect_contributions(
            FakeBuzz(),
            "channel",
            [Delegation(hermes, "d" * 64)],
            not_before=100,
            timeout_secs=10,
            poll_secs=3,
            clock=lambda: next(times),
            sleeper=sleeps.append,
        )
        self.assertEqual(contributions, [])
        self.assertEqual(timed_out, ["hermes"])
        self.assertEqual(calls, [10.0])
        self.assertEqual(sleeps, [0.5])

    def test_collection_does_not_fetch_after_deadline(self):
        hermes = Worker("hermes", "hermes-learning", "a" * 64, "architecture", ())
        times = iter((0.0, 10.0))

        class FakeBuzz:
            def get(self, channel_id, limit=100, timeout=None):
                raise AssertionError("collection fetched after deadline")

        contributions, timed_out = adapter.collect_contributions(
            FakeBuzz(), "channel", [Delegation(hermes, "d" * 64)],
            not_before=100, timeout_secs=10, poll_secs=3,
            clock=lambda: next(times), sleeper=lambda seconds: None,
        )
        self.assertEqual(contributions, [])
        self.assertEqual(timed_out, ["hermes"])

    def test_codex_synthesis_sanitizes_identity_environment_and_uses_last_message(self):
        calls = []

        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            return type("Completed", (), {
                "returncode": 0,
                "stdout": '\n'.join((
                    '{"type":"item.completed","item":{"type":"agent_message","text":"first"}}',
                    '{"type":"item.completed","item":{"type":"agent_message","text":"last"}}',
                )),
                "stderr": "",
            })()

        with tempfile.TemporaryDirectory() as state_dir:
            answer = adapter.run_codex_synthesis(
                "prompt", "session", subprocess_run=fake_run,
                environ={
                    "PATH": "/usr/bin", "CODEX_HOME": "/codex-home", "CODEX_MODE": "test",
                    "BUZZ_PRIVATE_KEY": "test-private-key", "BUZZ_RELAY_URL": "ws://relay",
                    "ORCHESTRATOR_IDENTITY_FILE": "/identity", "NOSTR_PRIVATE_KEY": "other-key",
                    "ORCHESTRATOR_CODEX_STATE_DIR": state_dir,
                    "ORCHESTRATOR_CODEX_WORKDIR": "/configured-workspace",
                },
            )

        self.assertEqual(answer, "last")
        command, kwargs = calls[0]
        self.assertEqual(command[:12], ["codex", "exec", "--json", "--ignore-user-config", "--ignore-rules", "--model", "gpt-5.5", "--sandbox", "read-only", "-C", "/configured-workspace", "--skip-git-repo-check"])
        self.assertEqual(command[-1], "-")
        self.assertEqual(kwargs["env"]["PATH"], "/usr/bin")
        self.assertEqual(kwargs["env"]["CODEX_HOME"], "/codex-home")
        self.assertEqual(kwargs["env"]["CODEX_MODE"], "test")
        self.assertNotIn("BUZZ_PRIVATE_KEY", kwargs["env"])
        self.assertNotIn("BUZZ_RELAY_URL", kwargs["env"])
        self.assertNotIn("ORCHESTRATOR_IDENTITY_FILE", kwargs["env"])
        self.assertNotIn("NOSTR_PRIVATE_KEY", kwargs["env"])
        self.assertEqual(kwargs["timeout"], 300)

    def test_codex_uses_output_file_only_when_no_agent_message_exists(self):
        def fake_run(command, **kwargs):
            output_file = Path(command[command.index("--output-last-message") + 1])
            output_file.write_text("fallback answer", encoding="utf-8")
            return type("Completed", (), {"returncode": 0, "stdout": '{"type":"item.started"}', "stderr": ""})()

        with tempfile.TemporaryDirectory() as state_dir:
            answer = adapter.run_codex_synthesis(
                "prompt", "session", subprocess_run=fake_run,
                environ={"PATH": "/usr/bin", "ORCHESTRATOR_CODEX_STATE_DIR": state_dir},
            )
        self.assertEqual(answer, "fallback answer")

    def test_codex_state_directory_defaults_to_in_scope_runtime_path(self):
        self.assertEqual(
            adapter.codex_state_dir({}),
            Path("/opt/orchestrator-state/codex-acp"),
        )

    def test_orchestration_skips_codex_when_every_worker_times_out(self):
        sent = []

        class FakeBuzz:
            def send(self, channel_id, content, **kwargs):
                sent.append(content)
                return "d" * 64

        workers = [{"slug": "hermes", "label": "hermes-learning", "pubkey": "a" * 64, "role": "architecture", "keywords": ["explain"]}]
        prompt = "Channel: #11111111-2222-3333-4444-555555555555\nEvent ID: " + "e" * 64 + "\nContent: @orchestrator-chat explain ACP"
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_WORKERS": json.dumps(workers)}):
            with mock.patch.object(adapter, "collect_contributions", return_value=([], ["hermes"])):
                with mock.patch.object(adapter, "run_codex_synthesis", side_effect=AssertionError("Codex must not run")):
                    adapter.orchestrate(prompt, "session", buzz=FakeBuzz())

        self.assertEqual(sum(item.startswith("[SYNTHESIS]") for item in sent), 1)
        self.assertEqual(
            sent[-1],
            "[SYNTHESIS]\nNo worker contributions arrived before the 90-second deadline.\nTimed out workers: hermes.",
        )

    def test_orchestration_publishes_one_synthesis_after_read_failures(self):
        sent = []

        class FailingBuzz:
            def send(self, channel_id, content, **kwargs):
                sent.append(content)
                return "d" * 64

            def get(self, channel_id, limit=100, timeout=None):
                raise RuntimeError("buzz messages get failed")

        workers = [{
            "slug": "hermes",
            "label": "hermes-learning",
            "pubkey": "a" * 64,
            "role": "architecture",
            "keywords": ["explain"],
        }]
        prompt = (
            "Channel: #11111111-2222-3333-4444-555555555555\nEvent ID: "
            + "e" * 64
            + "\nContent: @orchestrator-chat explain ACP"
        )
        times = iter((0.0, 0.0, 0.0, 90.0))
        try:
            with mock.patch.dict(os.environ, {"ORCHESTRATOR_WORKERS": json.dumps(workers)}):
                with mock.patch.object(
                    adapter.collect_contributions,
                    "__kwdefaults__",
                    {"clock": lambda: next(times), "sleeper": lambda seconds: None},
                ):
                    adapter.orchestrate(prompt, "session", buzz=FailingBuzz())
        except RuntimeError as exc:
            self.fail(f"Buzz read failure escaped real orchestration: {exc}")

        syntheses = [content for content in sent if content.startswith("[SYNTHESIS]")]
        self.assertEqual(len(syntheses), 1)
        self.assertEqual(
            syntheses[0],
            "[SYNTHESIS]\nNo worker contributions arrived before the 90-second deadline.\nTimed out workers: hermes.",
        )
        self.assertNotIn("buzz messages get failed", syntheses[0])

    def test_orchestration_appends_one_exact_timeout_attribution(self):
        sent = []

        class FakeBuzz:
            def send(self, channel_id, content, **kwargs):
                sent.append(content)
                return "d" * 64

        workers = [
            {"slug": "hermes", "label": "hermes-learning", "pubkey": "a" * 64, "role": "architecture", "keywords": ["explain"]},
            {"slug": "pi", "label": "pi-chat", "pubkey": "b" * 64, "role": "workflow", "keywords": ["workflow"]},
            {"slug": "codex", "label": "codex-chat", "pubkey": "c" * 64, "role": "implementation", "keywords": ["code"]},
        ]
        contribution = adapter.Contribution("hermes", "f" * 64, "Hermes answer")
        prompt = "Channel: #11111111-2222-3333-4444-555555555555\nEvent ID: " + "e" * 64 + "\nContent: @orchestrator-chat ask all agents to explain ACP"
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_WORKERS": json.dumps(workers)}):
            with mock.patch.object(
                adapter,
                "collect_contributions",
                return_value=([contribution], ["pi", "codex"]),
            ):
                with mock.patch.object(
                    adapter,
                    "run_codex_synthesis",
                    return_value="Hermes supplied the architecture contribution.",
                ):
                    adapter.orchestrate(prompt, "session", buzz=FakeBuzz())

        self.assertEqual(
            sent[-1],
            "[SYNTHESIS]\nHermes supplied the architecture contribution.\nTimed out workers: pi, codex.",
        )
        self.assertEqual(sent[-1].splitlines().count("Timed out workers: pi, codex."), 1)

    def test_orchestration_does_not_duplicate_exact_timeout_attribution(self):
        sent = []

        class FakeBuzz:
            def send(self, channel_id, content, **kwargs):
                sent.append(content)
                return "d" * 64

        workers = [
            {"slug": "hermes", "label": "hermes-learning", "pubkey": "a" * 64, "role": "architecture", "keywords": ["explain"]},
            {"slug": "pi", "label": "pi-chat", "pubkey": "b" * 64, "role": "workflow", "keywords": ["workflow"]},
            {"slug": "codex", "label": "codex-chat", "pubkey": "c" * 64, "role": "implementation", "keywords": ["code"]},
        ]
        contribution = adapter.Contribution("hermes", "f" * 64, "Hermes answer")
        prompt = "Channel: #11111111-2222-3333-4444-555555555555\nEvent ID: " + "e" * 64 + "\nContent: @orchestrator-chat ask all agents to explain ACP"
        model_answer = "Hermes supplied the architecture contribution.\nTimed out workers: pi, codex."
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_WORKERS": json.dumps(workers)}):
            with mock.patch.object(
                adapter,
                "collect_contributions",
                return_value=([contribution], ["pi", "codex"]),
            ):
                with mock.patch.object(
                    adapter,
                    "run_codex_synthesis",
                    return_value=model_answer,
                ):
                    adapter.orchestrate(prompt, "session", buzz=FakeBuzz())

        self.assertEqual(sent[-1], "[SYNTHESIS]\n" + model_answer)
        self.assertEqual(sent[-1].splitlines().count("Timed out workers: pi, codex."), 1)

    def test_long_synthesis_preserves_timeout_attribution_at_send_boundary(self):
        subprocess_inputs = []

        def fake_run(command, **kwargs):
            subprocess_inputs.append(kwargs["input"])
            return type(
                "Completed",
                (),
                {
                    "returncode": 0,
                    "stdout": '{"event_id":"' + "d" * 64 + '"}',
                    "stderr": "",
                },
            )()

        client = adapter.BuzzClient(
            subprocess_run=fake_run,
            environ={"BUZZ_PRIVATE_KEY": "test-private-key", "PATH": "/usr/bin"},
        )
        workers = [
            {"slug": "hermes", "label": "hermes-learning", "pubkey": "a" * 64, "role": "architecture", "keywords": ["explain"]},
            {"slug": "pi", "label": "pi-chat", "pubkey": "b" * 64, "role": "workflow", "keywords": ["workflow"]},
            {"slug": "codex", "label": "codex-chat", "pubkey": "c" * 64, "role": "implementation", "keywords": ["code"]},
        ]
        contribution = adapter.Contribution("hermes", "f" * 64, "Hermes answer")
        prompt = "Channel: #11111111-2222-3333-4444-555555555555\nEvent ID: " + "e" * 64 + "\nContent: @orchestrator-chat ask all agents to explain ACP"
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_WORKERS": json.dumps(workers)}):
            with mock.patch.object(
                adapter,
                "collect_contributions",
                return_value=([contribution], ["pi", "codex"]),
            ):
                with mock.patch.object(adapter, "run_codex_synthesis", return_value="A" * 5000):
                    adapter.orchestrate(prompt, "session", buzz=client)

        final_input = subprocess_inputs[-1]
        attribution = "Timed out workers: pi, codex."
        self.assertLessEqual(len(final_input), 3500)
        self.assertTrue(final_input.endswith("\n" + attribution))
        self.assertEqual(final_input.splitlines().count(attribution), 1)

    def test_orchestration_publishes_one_safe_final_message_after_codex_failure(self):
        sent = []

        class FakeBuzz:
            def send(self, channel_id, content, **kwargs):
                sent.append(content)
                return "d" * 64

        workers = [{"slug": "hermes", "label": "hermes-learning", "pubkey": "a" * 64, "role": "architecture", "keywords": ["explain"]}]
        contribution = adapter.Contribution("hermes", "c" * 64, "answer")
        prompt = "Channel: #11111111-2222-3333-4444-555555555555\nEvent ID: " + "e" * 64 + "\nContent: @orchestrator-chat explain ACP"
        with mock.patch.dict(os.environ, {"ORCHESTRATOR_WORKERS": json.dumps(workers)}):
            with mock.patch.object(adapter, "collect_contributions", return_value=([contribution], [])):
                with mock.patch.object(adapter, "run_codex_synthesis", side_effect=RuntimeError("unsafe stderr or key")):
                    adapter.orchestrate(prompt, "session", buzz=FakeBuzz())

        self.assertEqual(sum(item.startswith("[SYNTHESIS]") for item in sent), 1)
        self.assertEqual(sent[-1], "[SYNTHESIS]\nWorker contributions were collected, but Codex synthesis was unavailable. Please retry the request.")
        self.assertNotIn("unsafe stderr or key", sent[-1])

    def test_acp_prompt_emits_no_message_chunks(self):
        request_lines = "\n".join((
            '{"jsonrpc":"2.0","id":1,"method":"session/new","params":{}}',
            '{"jsonrpc":"2.0","id":2,"method":"session/prompt","params":{"sessionId":"orchestrator-1","prompt":[{"type":"text","text":"ignored"}]}}',
        )) + "\n"
        output = io.StringIO()
        with mock.patch.object(adapter.time, "time", return_value=0.001):
            with mock.patch.object(adapter, "orchestrate", return_value="published"):
                with mock.patch.object(adapter.sys, "stdin", io.StringIO(request_lines)):
                    with mock.patch.object(adapter.sys, "stdout", output):
                        adapter.run()

        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(messages[-1]["result"], {"stopReason": "end_turn"})
        self.assertFalse(any(message.get("method") == "session/update" for message in messages))

    def test_acp_non_object_requests_emit_errors_and_processing_continues(self):
        request_lines = "\n".join((
            "[]",
            "7",
            '"not-an-object"',
            '{"jsonrpc":"2.0","id":4,"method":"initialize","params":{"protocolVersion":2}}',
        )) + "\n"
        output = io.StringIO()

        try:
            with mock.patch.object(adapter.sys, "stdin", io.StringIO(request_lines)):
                with mock.patch.object(adapter.sys, "stdout", output):
                    result = adapter.run()
        except (AttributeError, TypeError) as exc:
            self.fail(f"non-object JSON terminated the ACP loop: {exc}")

        self.assertEqual(result, 0)
        messages = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(len(messages), 4)
        for response in messages[:3]:
            self.assertIsNone(response["id"])
            self.assertEqual(response["error"]["code"], -32600)
        self.assertEqual(messages[3]["id"], 4)
        self.assertEqual(messages[3]["result"]["protocolVersion"], 2)


if __name__ == "__main__":
    unittest.main()
