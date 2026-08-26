#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse, urlunparse


JSON = dict[str, Any]
HEX_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")


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
            "agentInfo": {"name": "codex-acp", "version": "local-learning"},
            "_meta": {"steering": {"supported": False}},
        },
    )


def extract_prompt_text(params: JSON) -> str:
    return "\n\n".join(extract_prompt_blocks(params))


def extract_prompt_blocks(params: JSON) -> list[str]:
    blocks = params.get("prompt") or []
    text_blocks: list[str] = []
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_blocks.append(text)
    return text_blocks


def parse_event_record(record: str) -> tuple[str, str, str] | None:
    match = re.match(
        r"^Event ID:\s*([0-9a-fA-F]{64})\s*\n"
        r"Channel:[^\r\n]*\n"
        r"Kind:\s*[0-9]+\s*\n"
        r"From:\s*[^\r\n]*\bhex:\s*([0-9a-fA-F]{64})\)\s*\n"
        r"Time:[^\r\n]*\n"
        r"Content:\s?(.*)\Z",
        record,
        re.DOTALL,
    )
    if not match:
        return None
    return match.group(1), match.group(2), match.group(3)


def trusted_current_event(prompt_blocks: Sequence[str]) -> tuple[str, str, str] | None:
    event_blocks = [
        block
        for block in prompt_blocks
        if block.startswith("[Buzz event:") or block.startswith("[Buzz events — ")
    ]
    if len(event_blocks) != 1:
        return None

    block = event_blocks[0]
    singular = re.match(r"^\[Buzz event: [^\]\r\n]+\]\n(.*)\Z", block, re.DOTALL)
    if singular:
        return parse_event_record(singular.group(1))

    batch = re.match(r"^\[Buzz events — ([1-9][0-9]*) events\]\n(.*)\Z", block, re.DOTALL)
    if not batch:
        return None

    advertised_count = int(batch.group(1))
    body = batch.group(2)
    delimiters = list(
        re.finditer(r"(?m)^--- Event ([0-9]+) \([^\r\n]*\) ---$", body)
    )
    if (
        len(delimiters) != advertised_count
        or [int(match.group(1)) for match in delimiters]
        != list(range(1, advertised_count + 1))
        or body[: delimiters[0].start()].strip()
    ):
        return None

    current_record = body[delimiters[-1].end() :].lstrip("\r\n")
    return parse_event_record(current_record)


def extract_buzz_routing(prompt_blocks: str | Sequence[str]) -> BuzzRouting:
    if isinstance(prompt_blocks, str):
        blocks = [prompt_blocks]
    else:
        blocks = list(prompt_blocks)
    prompt_text = "\n\n".join(blocks)
    channel_line_match = re.search(r"(?m)^Channel:\s*(.+?)\s*$", prompt_text)
    if not channel_line_match:
        raise RuntimeError("could not find Buzz channel id in ACP prompt")
    channel_line = channel_line_match.group(1)

    uuid_pattern = r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
    channel_match = (
        re.search(r"#" + uuid_pattern, channel_line)
        or re.search(r"^" + uuid_pattern, channel_line)
        or re.search(uuid_pattern, channel_line)
    )
    if not channel_match:
        raise RuntimeError("could not find Buzz channel id in ACP prompt")

    current_event = trusted_current_event(blocks)
    configured_orchestrator = os.environ.get("CODEX_ACP_ORCHESTRATOR_PUBKEY", "")
    is_orchestrator_delegation = (
        HEX_KEY_PATTERN.fullmatch(configured_orchestrator) is not None
        and current_event is not None
        and current_event[1].lower() == configured_orchestrator.lower()
        and "[ASK:CODEX]" in current_event[2]
    )

    if is_orchestrator_delegation:
        reply_to = current_event[0]
    else:
        reply_match = re.search(r"--reply-to\s+([0-9a-fA-F]{64})\b", prompt_text)
        if not reply_match:
            event_match = re.search(r"(?m)^Event ID:\s*([0-9a-fA-F]{64})\b", prompt_text)
            reply_to = event_match.group(1) if event_match else None
        else:
            reply_to = reply_match.group(1)

    return BuzzRouting(channel_id=channel_match.group(1), reply_to=reply_to)


def build_codex_prompt(prompt_text: str) -> str:
    model = os.environ.get("CODEX_ACP_MODEL", "gpt-5.5")
    sandbox = os.environ.get("CODEX_ACP_SANDBOX", "read-only")
    workdir = os.environ.get("CODEX_ACP_WORKDIR", "/workspace")
    transport = os.environ.get(
        "CODEX_ACP_TRANSPORT_DESCRIPTION",
        "Buzz -> buzz-acp -> codex-acp -> codex exec -> Codex/OpenAI provider -> Buzz",
    )
    return (
        "You are codex-chat, a conversational Buzz learning agent backed by the "
        "Codex CLI. Answer naturally and directly. Keep responses concise unless "
        "the user asks for details. Do not try to run `buzz messages send`; the "
        "adapter will publish your final plain-text answer back to Buzz. If asked "
        "about your runtime, provider, model, tools, or architecture, use these "
        "current local lab facts:\n"
        "- agent name: codex-chat\n"
        "- provider/runtime: Codex CLI using the signed-in Codex subscription\n"
        f"- model: {model}\n"
        f"- sandbox: {sandbox}\n"
        f"- workspace: {workdir}\n"
        f"- transport path: {transport}\n\n"
        f"{prompt_text}"
    )


def default_codex_command(output_file: Path) -> list[str]:
    return [
        "codex",
        "exec",
        "--json",
        "--ignore-user-config",
        "--ignore-rules",
        "--model",
        os.environ.get("CODEX_ACP_MODEL", "gpt-5.5"),
        "--sandbox",
        os.environ.get("CODEX_ACP_SANDBOX", "read-only"),
        "-C",
        os.environ.get("CODEX_ACP_WORKDIR", "/workspace"),
        "--skip-git-repo-check",
        "--output-last-message",
        str(output_file),
        "-",
    ]


def collect_codex_answer(lines: Iterable[str], output_file: Path | None = None) -> str:
    final_text: str | None = None
    for raw_line in lines:
        if not raw_line:
            continue
        event = json.loads(raw_line)
        if event.get("type") == "item.completed":
            item = event.get("item") or {}
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                final_text = item["text"]

    if final_text:
        return final_text.strip()
    if output_file and output_file.exists():
        return output_file.read_text(encoding="utf-8").strip()
    return ""


def run_codex(prompt_text: str, session_id: str) -> str:
    state_dir = Path(os.environ.get("CODEX_ACP_STATE_DIR", "/tmp/codex-acp")).resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    output_file = state_dir / f"{session_id}-{int(time.time() * 1000)}.txt"
    command = default_codex_command(output_file)
    timeout = int(os.environ.get("CODEX_ACP_TIMEOUT_SECS", "900"))

    completed = subprocess.run(
        command,
        input=build_codex_prompt(prompt_text),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "codex exec failed").strip()
        raise RuntimeError(detail[:1500])

    answer = collect_codex_answer(completed.stdout.splitlines(), output_file=output_file)
    return answer.strip()


def relay_http_url(relay_url: str) -> str:
    parsed = urlparse(relay_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme or "http")
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def publish_to_buzz(routing: BuzzRouting, text: str) -> None:
    if os.environ.get("CODEX_ACP_DRY_RUN") == "1":
        return
    relay_url = relay_http_url(os.environ.get("BUZZ_RELAY_URL", "ws://buzz.localtest.me:3300"))
    private_key = os.environ.get("BUZZ_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("BUZZ_PRIVATE_KEY is required to publish Codex's Buzz reply")

    buzz_cli = os.environ.get("CODEX_ACP_BUZZ_CLI", "/buzz-bin/buzz")
    cmd = [
        buzz_cli,
        "messages",
        "send",
        "--channel",
        routing.channel_id,
        "--content",
        "-",
    ]
    if routing.reply_to:
        cmd.extend(["--reply-to", routing.reply_to])

    completed = subprocess.run(
        cmd,
        input=text[:3500],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "BUZZ_RELAY_URL": relay_url, "BUZZ_PRIVATE_KEY": private_key},
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "buzz messages send failed").strip()[:1000])


def run() -> int:
    sessions: set[str] = set()
    for raw_line in sys.stdin:
        try:
            request = json.loads(raw_line)
            method = request.get("method")
            request_id = request.get("id")
            params = request.get("params") or {}

            if method == "initialize":
                write_json(handle_initialize(request))
            elif method == "authenticate":
                write_json(rpc_result(request_id, {}))
            elif method == "session/new":
                session_id = f"codex-chat-{int(time.time() * 1000)}"
                sessions.add(session_id)
                write_json(rpc_result(request_id, {"sessionId": session_id}))
            elif method == "session/prompt":
                session_id = params.get("sessionId")
                if session_id not in sessions:
                    raise RuntimeError(f"unknown sessionId: {session_id}")
                prompt_blocks = extract_prompt_blocks(params)
                prompt_text = "\n\n".join(prompt_blocks)
                routing = extract_buzz_routing(prompt_blocks)
                answer = run_codex(prompt_text, str(session_id))
                if not answer:
                    answer = "Codex completed the turn but did not produce a text answer."
                publish_to_buzz(routing, answer)
                write_json(rpc_result(request_id, {"stopReason": "end_turn"}))
            elif method == "session/cancel":
                write_json(rpc_result(request_id, {}))
            elif method in {"session/set_model", "session/set_config_option"}:
                write_json(rpc_result(request_id, {}))
            else:
                write_json(rpc_error(request_id, f"unsupported ACP method: {method}", code=-32601))
        except Exception as exc:
            request_id = None
            try:
                request_id = json.loads(raw_line).get("id")
            except Exception:
                pass
            write_json(rpc_error(request_id, str(exc)))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
