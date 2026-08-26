#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlparse, urlunparse


JSON = dict[str, Any]


def log(message: str) -> None:
    print(f"[pi-acp-poller] {message}", file=sys.stderr, flush=True)


def relay_http_url(relay_url: str) -> str:
    parsed = urlparse(relay_url)
    scheme = {"ws": "http", "wss": "https"}.get(parsed.scheme, parsed.scheme or "http")
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def parse_channel_ids(raw: str) -> list[str]:
    channel_ids: list[str] = []
    seen: set[str] = set()
    for item in raw.split(","):
        channel_id = item.strip()
        if channel_id and channel_id not in seen:
            channel_ids.append(channel_id)
            seen.add(channel_id)
    return channel_ids


def resolve_channel_ids(environ: Mapping[str, str] | None = None) -> list[str]:
    env = os.environ if environ is None else environ
    channel_ids = parse_channel_ids(
        env.get("PI_CHAT_CHANNELS")
        or env.get("PI_CHAT_CHANNEL_ID", "")
    )
    if not channel_ids:
        raise RuntimeError("PI_CHAT_CHANNELS or PI_CHAT_CHANNEL_ID is required")
    return channel_ids


def load_seen(path: Path) -> set[str]:
    try:
        raw = json.loads(path.read_text())
        ids = raw.get("seen_ids") if isinstance(raw, dict) else raw
        if isinstance(ids, list):
            return {str(event_id) for event_id in ids}
    except FileNotFoundError:
        return set()
    except Exception as exc:
        log(f"could not read seen file {path}: {exc}")
    return set()


def save_seen(path: Path, seen: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen_ids": sorted(seen)[-1000:]}, indent=2) + "\n")


def event_has_tag(event: JSON, tag_name: str, tag_value: str) -> bool:
    for tag in event.get("tags") or []:
        if isinstance(tag, list) and len(tag) >= 2 and tag[0] == tag_name and tag[1] == tag_value:
            return True
    return False


def event_textually_addresses_alias(event: JSON, aliases: list[str]) -> bool:
    content = str(event.get("content") or "").strip()
    for alias in aliases:
        normalized = alias.strip()
        if not normalized:
            continue
        pattern = rf"^@?{re.escape(normalized)}(?:\b|[\s,:-])"
        if re.search(pattern, content, flags=re.IGNORECASE):
            return True
    return False


def event_mentions_agent(event: JSON, agent_pubkey: str, aliases: list[str]) -> bool:
    return event_has_tag(event, "p", agent_pubkey) or event_textually_addresses_alias(event, aliases)


def buzz_messages_get(channel_id: str, limit: int) -> list[JSON]:
    buzz_cli = os.environ.get("PI_ACP_BUZZ_CLI", "/buzz-bin/buzz")
    relay_url = relay_http_url(os.environ.get("BUZZ_RELAY_URL", "ws://buzz.localtest.me:3300"))
    completed = subprocess.run(
        [buzz_cli, "messages", "get", "--channel", channel_id, "--limit", str(limit)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env={**os.environ, "BUZZ_RELAY_URL": relay_url},
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or "buzz messages get failed").strip())
    data = json.loads(completed.stdout or "[]")
    return data if isinstance(data, list) else []


class AcpClient:
    def __init__(self) -> None:
        command = os.environ.get("PI_ACP_ADAPTER_COMMAND", "python3 /usr/local/bin/pi-acp").split()
        self.proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            text=True,
            bufsize=1,
        )
        if self.proc.stdin is None or self.proc.stdout is None:
            raise RuntimeError("failed to start pi-acp")
        self.next_id = 1
        self.session_id: str | None = None
        self.call("initialize", {"protocolVersion": 2})
        new_session = self.call(
            "session/new",
            {
                "_meta": {
                    "systemPrompt": {
                        "append": os.environ.get("BUZZ_ACP_SYSTEM_PROMPT", ""),
                    }
                }
            },
        )
        self.session_id = str(new_session["sessionId"])
        log(f"started ACP session {self.session_id}")

    def call(self, method: str, params: JSON) -> JSON:
        assert self.proc.stdin is not None
        assert self.proc.stdout is not None
        request_id = self.next_id
        self.next_id += 1
        self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}) + "\n")
        self.proc.stdin.flush()
        while True:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("pi-acp exited before returning an ACP response")
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(message["error"].get("message", "ACP call failed"))
            result = message.get("result") or {}
            return result if isinstance(result, dict) else {}

    def prompt(self, prompt_text: str) -> None:
        if not self.session_id:
            raise RuntimeError("ACP session is not initialized")
        self.call(
            "session/prompt",
            {
                "sessionId": self.session_id,
                "prompt": [{"type": "text", "text": prompt_text}],
            },
        )


def prompt_for_event(event: JSON, channel_id: str, channel_name: str) -> str:
    event_id = str(event["id"])
    content = str(event.get("content") or "")
    author = str(event.get("pubkey") or "")
    return f"""[Context]
Scope: channel
Channel: {channel_name} (#{channel_id})

[Buzz event: @mention]
Event ID: {event_id}
Author: {author}
Content: {content}
IMPORTANT: This is a new top-level message. For ordinary replies in this turn, use `--reply-to {event_id}` on `buzz messages send`.
"""


def poll_channels_once(
    channel_ids: list[str],
    limit: int,
    agent_pubkey: str,
    agent_aliases: list[str],
    allowlist: set[str],
    startup_floor: int,
    seen: set[str],
    acp: AcpClient,
    state_path: Path,
    channel_name: str = "Pi Chat",
    fetch_messages: Callable[[str, int], list[JSON]] = buzz_messages_get,
) -> bool:
    changed = False
    for channel_id in channel_ids:
        try:
            events = fetch_messages(channel_id, limit)
            for event in sorted(events, key=lambda item: int(item.get("created_at") or 0)):
                event_id = str(event.get("id") or "")
                if not event_id or event_id in seen:
                    continue
                created_at = int(event.get("created_at") or 0)
                if created_at < startup_floor:
                    seen.add(event_id)
                    changed = True
                    continue
                author = str(event.get("pubkey") or "").lower()
                if author == agent_pubkey.lower():
                    seen.add(event_id)
                    changed = True
                    continue
                if allowlist and author not in allowlist:
                    log(f"skipping non-allowlisted author for event {event_id[:12]}")
                    seen.add(event_id)
                    changed = True
                    continue
                if not event_mentions_agent(event, agent_pubkey, agent_aliases):
                    continue
                log(f"handling mention event {event_id[:12]}")
                acp.prompt(prompt_for_event(event, channel_id, channel_name))
                seen.add(event_id)
                changed = True
                save_seen(state_path, seen)
        except Exception as exc:
            log(f"poll channel {channel_id} error: {exc}")
    if changed:
        save_seen(state_path, seen)
    return changed


def main() -> int:
    channel_ids = resolve_channel_ids()
    agent_pubkey = os.environ["PI_CHAT_PUBKEY"]
    channel_name = os.environ.get("PI_CHAT_CHANNEL_NAME", "Pi Chat")
    agent_aliases = [
        item.strip()
        for item in os.environ.get("PI_ACP_AGENT_ALIASES", "pi-chat").split(",")
        if item.strip()
    ]
    allowlist = {
        item.strip().lower()
        for item in os.environ.get("BUZZ_ACP_RESPOND_TO_ALLOWLIST", "").split(",")
        if item.strip()
    }
    poll_secs = float(os.environ.get("PI_ACP_POLL_INTERVAL_SECS", "4"))
    replay_secs = int(os.environ.get("PI_ACP_POLL_REPLAY_SECS", "600"))
    limit = int(os.environ.get("PI_ACP_POLL_LIMIT", "30"))
    state_path = Path(os.environ.get("PI_ACP_POLL_STATE", "/opt/pi/state/pi-agent/pi-chat-acp-poller-seen.json"))
    seen = load_seen(state_path)
    acp = AcpClient()
    startup_floor = int(time.time()) - replay_secs
    log(f"watching channels {', '.join(channel_ids)} for mentions of {agent_pubkey}")

    while True:
        try:
            poll_channels_once(
                channel_ids,
                limit,
                agent_pubkey,
                agent_aliases,
                allowlist,
                startup_floor,
                seen,
                acp,
                state_path,
                channel_name=channel_name,
                fetch_messages=buzz_messages_get,
            )
        except Exception as exc:
            log(f"poll loop error: {exc}")
        time.sleep(poll_secs)


if __name__ == "__main__":
    raise SystemExit(main())
