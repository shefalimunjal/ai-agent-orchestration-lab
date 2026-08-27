#!/usr/bin/env python3
"""ACP v2 adapter that coordinates bounded Buzz worker contributions."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence
from urllib.parse import urlparse, urlunparse

from orchestrator_core import (
    Contribution,
    Delegation,
    Worker,
    build_synthesis_prompt,
    build_worker_prompt,
    find_contribution,
    select_workers,
)


JSON = dict[str, Any]
EVENT_ID_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
DEFAULT_CODEX_STATE_DIR = Path("/opt/orchestrator-state/codex-acp")
SAFE_SYNTHESIS_FAILURE = "Worker contributions were collected, but Codex synthesis was unavailable. Please retry the request."


@dataclass(frozen=True)
class BuzzRouting:
    channel_id: str
    reply_to: str | None


def rpc_result(request_id: Any, result: JSON) -> JSON:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def rpc_error(request_id: Any, message: str, code: int = -32000) -> JSON:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def write_json(value: JSON) -> None:
    sys.stdout.write(json.dumps(value, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def handle_initialize(request: JSON) -> JSON:
    request_version = int((request.get("params") or {}).get("protocolVersion") or 1)
    return rpc_result(
        request.get("id"),
        {
            "protocolVersion": min(request_version, 2),
            "agentCapabilities": {},
            "authMethods": [],
            "agentInfo": {"name": "orchestrator-acp", "version": "local-learning"},
            "_meta": {"steering": {"supported": False}},
        },
    )


def extract_prompt_text(params: JSON) -> str:
    blocks = params.get("prompt") or []
    if not isinstance(blocks, list):
        return ""
    return "\n\n".join(
        block["text"]
        for block in blocks
        if isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str)
        and block["text"]
    )


def extract_buzz_routing(prompt_text: str) -> BuzzRouting:
    channel_match = re.search(
        r"(?m)^Channel:\s*.*?#([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b",
        prompt_text,
    )
    if not channel_match:
        channel_match = re.search(
            r"(?m)^Channel:\s*([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b",
            prompt_text,
        )
    if not channel_match:
        raise RuntimeError("could not find Buzz channel id in ACP prompt")

    reply_match = re.search(r"--reply-to\s+([0-9a-fA-F]{64})\b", prompt_text)
    if not reply_match:
        reply_match = re.search(r"(?m)^Event ID:\s*([0-9a-fA-F]{64})\b", prompt_text)
    return BuzzRouting(channel_id=channel_match.group(1), reply_to=reply_match.group(1) if reply_match else None)


def extract_human_task(prompt_text: str) -> str:
    content_match = re.search(r"(?m)^Content:\s*(.+?)\s*$", prompt_text)
    if not content_match:
        raise RuntimeError("could not find human content in ACP prompt")
    task = re.sub(r"^@[A-Za-z0-9_-]+\s*", "", content_match.group(1)).strip()
    if not task:
        raise RuntimeError("Buzz event does not contain a human task")
    return task


def relay_http_url(relay_url: str) -> str:
    parsed = urlparse(relay_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme or "http")
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def parse_send_event_id(output: str) -> str:
    try:
        decoded = json.loads(output)
    except json.JSONDecodeError as exc:
        raise RuntimeError("buzz messages send did not return JSON event_id") from exc
    event_id = decoded.get("event_id") if isinstance(decoded, dict) else None
    if not isinstance(event_id, str) or not EVENT_ID_PATTERN.fullmatch(event_id):
        raise RuntimeError("buzz messages send response requires a 64-hex event_id")
    return event_id


class BuzzClient:
    """Small subprocess boundary for Buzz CLI calls; it never logs credentials."""

    def __init__(
        self,
        *,
        subprocess_run: Callable[..., Any] = subprocess.run,
        environ: Mapping[str, str] | None = None,
        buzz_cli: str = "/buzz-bin/buzz",
    ) -> None:
        self._run = subprocess_run
        self._environ = dict(os.environ if environ is None else environ)
        self._buzz_cli = buzz_cli

    def _environment(self) -> dict[str, str]:
        private_key = self._environ.get("BUZZ_PRIVATE_KEY")
        if not private_key:
            raise RuntimeError("BUZZ_PRIVATE_KEY is required for Buzz CLI calls")
        environment = {
            name: self._environ[name]
            for name in ("PATH", "HOME", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "NODE_EXTRA_CA_CERTS")
            if name in self._environ
        }
        environment["BUZZ_PRIVATE_KEY"] = private_key
        environment["BUZZ_RELAY_URL"] = relay_http_url(
            self._environ.get("BUZZ_RELAY_URL", "ws://buzz.localtest.me:3300")
        )
        return environment

    def send(
        self,
        channel_id: str,
        content: str,
        *,
        reply_to: str | None = None,
        mention: str | None = None,
    ) -> str:
        command = [self._buzz_cli, "messages", "send", "--channel", channel_id, "--content", "-"]
        if reply_to:
            command.extend(["--reply-to", reply_to])
        if mention:
            command.extend(["--mention", mention])
        completed = self._run(
            command,
            input=content[:3500],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environment(),
            timeout=float(self._environ.get("ORCHESTRATOR_BUZZ_TIMEOUT_SECS", "30")),
        )
        if completed.returncode != 0:
            raise RuntimeError("buzz messages send failed")
        return parse_send_event_id(completed.stdout)

    def get(self, channel_id: str, limit: int = 100, *, timeout: float | None = None) -> list[JSON]:
        command_timeout = timeout
        if command_timeout is None:
            command_timeout = float(self._environ.get("ORCHESTRATOR_BUZZ_TIMEOUT_SECS", "30"))
        completed = self._run(
            [self._buzz_cli, "messages", "get", "--channel", channel_id, "--limit", str(limit)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._environment(),
            timeout=command_timeout,
        )
        if completed.returncode != 0:
            raise RuntimeError("buzz messages get failed")
        try:
            events = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError("buzz messages get did not return JSON") from exc
        if not isinstance(events, list):
            raise RuntimeError("buzz messages get must return a JSON array")
        return events


def _worker_from_dict(value: Any) -> Worker:
    if not isinstance(value, dict):
        raise RuntimeError("ORCHESTRATOR_WORKERS entries must be JSON objects")
    try:
        slug = str(value["slug"])
        label = str(value["label"])
        pubkey = str(value["pubkey"])
        role = str(value["role"])
        keywords = tuple(str(item) for item in value["keywords"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("ORCHESTRATOR_WORKERS entries require slug, label, pubkey, role, and keywords") from exc
    if not EVENT_ID_PATTERN.fullmatch(pubkey):
        raise RuntimeError(f"invalid worker public key for {slug}")
    return Worker(slug, label, pubkey, role, keywords)


def load_workers_from_env(environ: Mapping[str, str] | None = None) -> list[Worker]:
    values = os.environ if environ is None else environ
    raw_workers = values.get("ORCHESTRATOR_WORKERS")
    if raw_workers:
        try:
            configured = json.loads(raw_workers)
        except json.JSONDecodeError as exc:
            raise RuntimeError("ORCHESTRATOR_WORKERS must be a JSON array") from exc
        if not isinstance(configured, list) or not configured:
            raise RuntimeError("ORCHESTRATOR_WORKERS must be a non-empty JSON array")
        return [_worker_from_dict(item) for item in configured]

    defaults = (
        ("hermes", "hermes-learning", "architecture and teaching", ("architecture", "explain", "learn", "concept")),
        ("pi", "pi-chat", "workflow and harness", ("workflow", "harness", "process", "contract", "steps")),
        ("codex", "codex-chat", "implementation and verification", ("code", "repo", "implement", "test", "debug", "verify")),
    )
    workers: list[Worker] = []
    for slug, label, role, keywords in defaults:
        public_key = values.get(f"ORCHESTRATOR_{slug.upper()}_PUBKEY")
        if not public_key:
            raise RuntimeError("ORCHESTRATOR_WORKERS or each ORCHESTRATOR_*_PUBKEY is required")
        workers.append(Worker(slug, label, public_key, role, keywords))
    return workers


def task_summary(task: str, workers: Sequence[Worker]) -> str:
    return "Task: " + task.strip() + "\nDelegated workers: " + ", ".join(worker.slug for worker in workers)


def ensure_timeout_attribution(answer: str, timed_out: Sequence[str]) -> str:
    if not timed_out:
        return answer
    attribution = "Timed out workers: " + ", ".join(timed_out) + "."
    lines = [line for line in answer.splitlines() if line != attribution]
    lines.append(attribution)
    return "\n".join(lines)


def build_synthesis_message(
    answer: str,
    timed_out: Sequence[str],
    *,
    max_chars: int = 3500,
) -> str:
    prefix = "[SYNTHESIS]\n"
    if not timed_out:
        return prefix + answer

    attribution = "Timed out workers: " + ", ".join(timed_out) + "."
    body = "\n".join(line for line in answer.splitlines() if line != attribution)
    suffix = "\n" + attribution
    body_budget = max(0, max_chars - len(prefix) - len(suffix))
    return prefix + body[:body_budget] + suffix


def collect_contributions(
    buzz: Any,
    channel_id: str,
    delegations: Sequence[Delegation],
    *,
    not_before: int,
    timeout_secs: int,
    poll_secs: int,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> tuple[list[Contribution], list[str]]:
    deadline = clock() + timeout_secs
    pending = list(delegations)
    found: dict[str, Contribution] = {}
    while pending:
        remaining = deadline - clock()
        if remaining <= 0:
            break
        try:
            events = buzz.get(channel_id, limit=100, timeout=remaining)
        except (subprocess.TimeoutExpired, RuntimeError):
            events = []
        still_pending: list[Delegation] = []
        for delegation in pending:
            contribution = find_contribution(events, delegation, not_before)
            if contribution is None:
                still_pending.append(delegation)
            else:
                found[delegation.worker.slug] = contribution
        pending = still_pending
        if not pending:
            break
        remaining = deadline - clock()
        if remaining <= 0:
            break
        sleeper(min(poll_secs, remaining))
    return (
        [found[delegation.worker.slug] for delegation in delegations if delegation.worker.slug in found],
        [delegation.worker.slug for delegation in pending],
    )


def collect_codex_answer(lines: Iterable[str], output_file: Path) -> str:
    answer = ""
    for line in lines:
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item") if event.get("type") == "item.completed" else None
        if isinstance(item, dict) and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
            answer = item["text"].strip()
    if answer:
        return answer
    if output_file.exists():
        fallback = output_file.read_text(encoding="utf-8").strip()
        if fallback:
            return fallback
    raise RuntimeError("codex synthesis did not produce an agent message")


def codex_state_dir(environ: Mapping[str, str]) -> Path:
    return Path(environ.get("ORCHESTRATOR_CODEX_STATE_DIR", str(DEFAULT_CODEX_STATE_DIR)))


def _is_identity_environment_variable(name: str) -> bool:
    upper_name = name.upper()
    return (
        upper_name.startswith("BUZZ_")
        or upper_name == "ORCHESTRATOR_IDENTITY_FILE"
        or bool(re.search(r"(?:^|_)(?:IDENTITY|PRIVATE|SECRET)(?:_|$)", upper_name))
    )


def sanitized_codex_environment(environ: Mapping[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in environ.items()
        if not _is_identity_environment_variable(name)
    }


def run_codex_synthesis(
    prompt_text: str,
    session_id: str,
    *,
    subprocess_run: Callable[..., Any] = subprocess.run,
    environ: Mapping[str, str] | None = None,
) -> str:
    values = os.environ if environ is None else environ
    state_dir = codex_state_dir(values)
    state_dir.mkdir(parents=True, exist_ok=True)
    output_file = state_dir / f"{session_id}-{int(time.time() * 1000)}.txt"
    timeout = min(max(int(values.get("ORCHESTRATOR_CODEX_TIMEOUT_SECS", "300")), 1), 300)
    workdir = values.get("ORCHESTRATOR_CODEX_WORKDIR", "/workspace")
    command = [
        "codex", "exec", "--json", "--ignore-user-config", "--ignore-rules", "--model", "gpt-5.5",
        "--sandbox", "read-only", "-C", workdir, "--skip-git-repo-check", "--output-last-message",
        str(output_file), "-",
    ]
    completed = subprocess_run(
        command,
        input=prompt_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        env=sanitized_codex_environment(values),
    )
    if completed.returncode != 0:
        raise RuntimeError("codex synthesis failed")
    return collect_codex_answer(completed.stdout.splitlines(), output_file)


def orchestrate(prompt_text: str, session_id: str, *, buzz: BuzzClient | None = None) -> str:
    routing = extract_buzz_routing(prompt_text)
    if not routing.reply_to:
        raise RuntimeError("could not find root Buzz event id in ACP prompt")
    task = extract_human_task(prompt_text)
    workers = select_workers(task, load_workers_from_env())
    client = buzz or BuzzClient(
        buzz_cli=os.environ.get("ORCHESTRATOR_BUZZ_CLI", "/buzz-bin/buzz")
    )
    client.send(routing.channel_id, "[TASK]\n" + task_summary(task, workers), reply_to=routing.reply_to)
    delegations = [
        Delegation(
            worker,
            client.send(
                routing.channel_id,
                build_worker_prompt(task, worker),
                reply_to=routing.reply_to,
                mention=worker.pubkey,
            ),
            routing.reply_to,
        )
        for worker in workers
    ]
    contributions, timed_out = collect_contributions(
        client,
        routing.channel_id,
        delegations,
        not_before=int(time.time()) - 2,
        timeout_secs=90,
        poll_secs=3,
    )
    if contributions:
        try:
            answer = run_codex_synthesis(build_synthesis_prompt(task, contributions, timed_out), session_id)
        except Exception:
            answer = SAFE_SYNTHESIS_FAILURE
    else:
        answer = "No worker contributions arrived before the 90-second deadline."
    answer = ensure_timeout_attribution(answer, timed_out)
    client.send(
        routing.channel_id,
        build_synthesis_message(answer, timed_out),
        reply_to=routing.reply_to,
    )
    return answer


def run() -> int:
    sessions: set[str] = set()
    for raw_line in sys.stdin:
        request: Any = {}
        request_id: Any = None
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                write_json(rpc_error(None, "invalid JSON-RPC request", code=-32600))
                continue
            method = request.get("method")
            request_id = request.get("id")
            params = request.get("params") or {}
            if method == "initialize":
                write_json(handle_initialize(request))
            elif method == "authenticate":
                write_json(rpc_result(request_id, {}))
            elif method == "session/new":
                session_id = f"orchestrator-{int(time.time() * 1000)}"
                sessions.add(session_id)
                write_json(rpc_result(request_id, {"sessionId": session_id}))
            elif method == "session/prompt":
                session_id = params.get("sessionId")
                if session_id not in sessions:
                    raise RuntimeError(f"unknown sessionId: {session_id}")
                orchestrate(extract_prompt_text(params), str(session_id))
                write_json(rpc_result(request_id, {"stopReason": "end_turn"}))
            elif method == "session/cancel":
                write_json(rpc_result(request_id, {}))
            elif method in {"session/set_model", "session/set_config_option"}:
                write_json(rpc_result(request_id, {}))
            else:
                write_json(rpc_error(request_id, f"unsupported ACP method: {method}", code=-32601))
        except Exception as exc:
            write_json(rpc_error(request_id, str(exc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
