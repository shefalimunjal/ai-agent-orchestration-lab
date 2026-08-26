#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator
from urllib.parse import urlparse, urlunparse


JSON = dict[str, Any]


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
            "agentInfo": {"name": "pi-acp", "version": "local-learning"},
            "_meta": {"steering": {"supported": False}},
        },
    )


def extract_prompt_text(params: JSON) -> str:
    blocks = params.get("prompt") or []
    text_blocks: list[str] = []
    if isinstance(blocks, list):
        for block in blocks:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text:
                    text_blocks.append(text)
    return "\n\n".join(text_blocks)


def extract_buzz_routing(prompt_text: str) -> BuzzRouting:
    channel_line_match = re.search(r"(?m)^Channel:\s*(.+?)\s*$", prompt_text)
    if not channel_line_match:
        raise RuntimeError("could not find Buzz channel id in ACP prompt")
    channel_line = channel_line_match.group(1)

    uuid_pattern = r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b"
    channel_match = re.search(r"#" + uuid_pattern, channel_line) or re.search(r"^" + uuid_pattern, channel_line) or re.search(uuid_pattern, channel_line)
    if not channel_match:
        raise RuntimeError("could not find Buzz channel id in ACP prompt")

    reply_match = re.search(r"--reply-to\s+([0-9a-fA-F]{64})\b", prompt_text)
    if not reply_match:
        event_match = re.search(r"(?m)^Event ID:\s*([0-9a-fA-F]{64})\b", prompt_text)
        reply_to = event_match.group(1) if event_match else None
    else:
        reply_to = reply_match.group(1)

    return BuzzRouting(channel_id=channel_match.group(1), reply_to=reply_to)


def acp_message_chunk(session_id: str, text: str, message_id: str = "pi-acp-answer") -> JSON:
    return {
        "jsonrpc": "2.0",
        "method": "session/update",
        "params": {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "agent_message_chunk",
                "messageId": message_id,
                "content": {"type": "text", "text": text},
            },
        },
    }


def collect_pi_answer(
    lines: Iterable[str],
    *,
    session_id: str,
    emit_update: Callable[[JSON], None],
) -> str:
    chunks: list[str] = []
    final_text: str | None = None
    for raw_line in lines:
        if not raw_line:
            continue
        event = json.loads(raw_line)
        event_type = event.get("type")
        if event_type == "extension_ui_request":
            if "request" in event:
                raise RuntimeError("interactive Pi request is not supported in pi-acp learning mode")
            continue
        if event_type == "message_update":
            assistant_event = event.get("assistantMessageEvent") or {}
            if assistant_event.get("type") == "text_delta":
                delta = str(assistant_event.get("delta") or "")
                if delta:
                    chunks.append(delta)
                    emit_update(acp_message_chunk(session_id, delta))
            elif assistant_event.get("type") == "text_end":
                content = assistant_event.get("content")
                if isinstance(content, str):
                    final_text = content
        elif event_type == "agent_end":
            break

    answer = final_text if final_text is not None else "".join(chunks)
    return answer.strip()


def build_pi_prompt(prompt_text: str) -> str:
    provider = os.environ.get("PI_ACP_PROVIDER", "openai-codex")
    model = os.environ.get("PI_ACP_MODEL", "gpt-5.5")
    thinking = os.environ.get("PI_ACP_THINKING", "low")
    tools = os.environ.get("PI_ACP_TOOLS", "read,grep,find,ls")
    transport = os.environ.get(
        "PI_ACP_TRANSPORT_DESCRIPTION",
        "Buzz -> pi-chat ACP poll bridge -> pi-acp -> Pi RPC -> Codex/OpenAI provider -> Buzz",
    )
    return (
        "You are pi-chat, a conversational Buzz agent powered by the real Pi CLI "
        "through a local ACP shim. Answer naturally and directly for learning. "
        "Do not try to run `buzz messages send`; the adapter will publish your final "
        "plain-text answer back to Buzz. If asked about your runtime, provider, "
        "model, tools, or architecture, use these current local lab facts:\n"
        f"- provider: {provider}\n"
        f"- model: {model}\n"
        f"- thinking/reasoning: {thinking}\n"
        f"- allowed tools: {tools}\n"
        f"- transport path: {transport}\n"
        "The official buzz-acp websocket service exists in this lab, but this running "
        "pi-chat service currently uses the poll bridge because local websocket wakeup "
        "was intermittent during testing.\n\n"
        f"{prompt_text}"
    )


def default_pi_command(system_prompt: str | None) -> list[str]:
    pi_args = [
        "pi",
        "--mode",
        "rpc",
        "--provider",
        os.environ.get("PI_ACP_PROVIDER", "openai-codex"),
        "--model",
        os.environ.get("PI_ACP_MODEL", "gpt-5.5"),
        "--thinking",
        os.environ.get("PI_ACP_THINKING", "low"),
        "--session-dir",
        "/opt/pi/state/pi-agent/sessions/pi-chat-acp",
        "--name",
        "pi-chat",
        "--tools",
        os.environ.get("PI_ACP_TOOLS", "read,grep,find,ls"),
        "--approve",
    ]
    if os.environ.get("PI_ACP_DIRECT_PI") != "1":
        pi_args = [
            "docker",
            "exec",
            "-i",
            "learning-pi-runner",
            "env",
            "PI_CODING_AGENT_DIR=/opt/pi/state/pi-agent",
            *pi_args,
        ]
    if system_prompt:
        pi_args.extend(["--append-system-prompt", system_prompt[:20000]])
    return pi_args


class PiSession:
    def __init__(self, session_id: str, system_prompt: str | None) -> None:
        self.session_id = session_id
        command = os.environ.get("PI_ACP_PI_COMMAND")
        args = shlex.split(command) if command else default_pi_command(system_prompt)
        self.proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("failed to open Pi RPC stdio")

    def prompt(self, text: str) -> str:
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        self.proc.stdin.write(json.dumps({"type": "prompt", "message": build_pi_prompt(text)}) + "\n")
        self.proc.stdin.flush()
        return collect_pi_answer(self.proc.stdout, session_id=self.session_id, emit_update=write_json)

    def cancel(self) -> None:
        if self.proc.stdin:
            self.proc.stdin.write(json.dumps({"type": "abort"}) + "\n")
            self.proc.stdin.flush()

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def relay_http_url(relay_url: str) -> str:
    parsed = urlparse(relay_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme or "http")
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def docker_proxy_ip() -> str:
    override = os.environ.get("PI_ACP_BUZZ_PROXY_IP")
    if override:
        return override
    completed = subprocess.run(
        ["docker", "inspect", "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", "learning-buzz-community-proxy"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        check=False,
    )
    return completed.stdout.strip() or "172.18.0.8"


def publish_to_buzz(routing: BuzzRouting, text: str) -> None:
    if os.environ.get("PI_ACP_DRY_RUN") == "1":
        return
    relay_url = relay_http_url(os.environ.get("BUZZ_RELAY_URL", "ws://buzz.localtest.me:3300"))
    private_key = os.environ.get("BUZZ_PRIVATE_KEY")
    if not private_key:
        raise RuntimeError("BUZZ_PRIVATE_KEY is required to publish Pi's Buzz reply")

    if os.environ.get("PI_ACP_DIRECT_BUZZ") == "1":
        buzz_cli = os.environ.get("PI_ACP_BUZZ_CLI", "/buzz-bin/buzz")
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
        return

    workspace = Path(os.environ.get("PI_ACP_WORKSPACE", os.getcwd())).resolve()
    buzz_bin = workspace / "workpods-buzz" / "hermes" / "buzz-bin"
    host = urlparse(relay_url).hostname or "buzz.localtest.me"
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        os.environ.get("PI_ACP_DOCKER_NETWORK", "workpods-learning"),
        "--add-host",
        f"{host}:{docker_proxy_ip()}",
        "-v",
        f"{buzz_bin}:/buzz-bin:ro",
        "-e",
        f"BUZZ_RELAY_URL={relay_url}",
        "-e",
        f"BUZZ_PRIVATE_KEY={private_key}",
        "rust:1.88-bookworm",
        "/buzz-bin/buzz",
        "messages",
        "send",
        "--channel",
        routing.channel_id,
        "--content",
        "-",
    ]
    if routing.reply_to:
        cmd.extend(["--reply-to", routing.reply_to])
    completed = subprocess.run(cmd, input=text[:3500], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "buzz messages send failed").strip()[:1000])


def run() -> int:
    sessions: dict[str, PiSession] = {}
    try:
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
                    session_id = f"pi-chat-{int(time.time() * 1000)}"
                    system_prompt = params.get("systemPrompt")
                    if not isinstance(system_prompt, str):
                        meta_prompt = (((params.get("_meta") or {}).get("systemPrompt") or {}).get("append"))
                        system_prompt = meta_prompt if isinstance(meta_prompt, str) else None
                    sessions[session_id] = PiSession(session_id, system_prompt)
                    write_json(rpc_result(request_id, {"sessionId": session_id}))
                elif method == "session/prompt":
                    session_id = params.get("sessionId")
                    if session_id not in sessions:
                        raise RuntimeError(f"unknown sessionId: {session_id}")
                    prompt_text = extract_prompt_text(params)
                    routing = extract_buzz_routing(prompt_text)
                    answer = sessions[session_id].prompt(prompt_text)
                    if not answer:
                        answer = "Pi completed the turn but did not produce a text answer."
                    publish_to_buzz(routing, answer)
                    write_json(rpc_result(request_id, {"stopReason": "end_turn"}))
                elif method == "session/cancel":
                    session_id = params.get("sessionId")
                    if session_id in sessions:
                        sessions[session_id].cancel()
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
    finally:
        for session in sessions.values():
            session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
