#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


BUZZ = os.environ.get("BUZZ_CLI_PATH", "/buzz-bin/buzz")
STATE_PATH = Path(os.environ.get("PI_BRIDGE_STATE", "/state/pi-bridge-state.json"))
CHANNEL_ID = os.environ["BUZZ_CHANNEL_ID"]
SELF_PUBKEY = os.environ["PI_LEARNING_PUBKEY"].lower()
HUMAN_PUBKEY = os.environ.get("HUMAN_PUBKEY", "").lower()
BOT_NAME = os.environ.get("PI_BRIDGE_NAME", "pi-learning")
RUNNER_URL = os.environ.get("PI_RUNNER_URL", "http://learning-pi-runner:8080").rstrip("/")
RUNNER_TOKEN = os.environ.get("PI_RUNNER_INGEST_TOKEN", "")
POLL_INTERVAL = float(os.environ.get("PI_BRIDGE_POLL_INTERVAL", "5"))


def log(message: str) -> None:
    print(message, flush=True)


def buzz(args: list[str], input_text: str | None = None, timeout: int = 45) -> Any:
    completed = subprocess.run(
        [BUZZ, *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
        env=os.environ.copy(),
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"buzz {' '.join(args[:2])} failed: {detail[:500]}")
    if not completed.stdout.strip():
        return None
    return json.loads(completed.stdout)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {"last_ts": 0, "seen": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"last_ts": 0, "seen": []}
    return {
        "last_ts": int(data.get("last_ts") or 0),
        "seen": [str(item) for item in data.get("seen", [])][-500:],
    }


def save_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    compact = {"last_ts": int(state.get("last_ts") or 0), "seen": list(state.get("seen", []))[-500:]}
    STATE_PATH.write_text(json.dumps(compact, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def event_mentions_self(event: dict[str, Any]) -> bool:
    tags = event.get("tags") or []
    for tag in tags:
        if isinstance(tag, list) and len(tag) > 1 and tag[0] == "p" and str(tag[1]).lower() == SELF_PUBKEY:
            return True
    content = str(event.get("content") or "").lower()
    name = re.escape(BOT_NAME.lower())
    return re.search(rf"(?<!\w)@?{name}(?!\w)", content) is not None


def strip_visible_mention(content: str) -> str:
    pattern = rf"^\s*@?{re.escape(BOT_NAME)}[\s:,\-–—]*"
    stripped = re.sub(pattern, "", content.strip(), count=1, flags=re.IGNORECASE)
    return stripped.strip() or content.strip()


def pi_run_for_message(event: dict[str, Any], prompt: str) -> dict[str, Any]:
    event_id = str(event["id"])
    body = {
        "run_id": f"buzz-{event_id[:24]}",
        "step_id": "buzz-learning-task",
        "workflow_slug": "buzz-pi-learning",
        "workflow_version": "local-v1",
        "profile": "workflow-fast",
        "prompt": (
            "You are pi-learning, a generic local Pi runner exposed in Buzz for learning. "
            "Answer the user's request compactly and explain what Pi runner boundary was exercised.\n\n"
            f"User request:\n{prompt}"
        ),
        "phase": "learning",
        "brand_id": "local-learning",
        "domain": "local.test",
        "model": {
            "provider": "openai-codex",
            "name": "gpt-5.5",
            "reasoning_effort": "low",
        },
        # The Pi runner treats an empty list as "use the default WorkPods MCP".
        # For the generic learning agent, request a deliberately non-existent
        # MCP name so the selected server set is empty and Pi stays model-only.
        "mcp": {"servers": ["__none__"]},
        "inputs": {"buzz_event_id": event_id, "buzz_channel_id": CHANNEL_ID},
        "output_contract": {"schema": "workpods.pi.step_result.v2", "step_required_fields": {}},
        "objective": prompt,
    }
    request = urllib.request.Request(
        f"{RUNNER_URL}/v1/runs",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RUNNER_TOKEN}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"pi-runner HTTP {exc.code}: {detail[:500]}") from exc


def reply_to_event(event: dict[str, Any], response: dict[str, Any]) -> None:
    status = response.get("status", "unknown")
    summary = str(response.get("summary") or "").strip()
    description = str(response.get("description") or "").strip()
    text = (
        f"Pi runner status: {status}\n\n"
        f"{summary}\n\n"
        f"{description}".strip()
    )
    args = ["messages", "send", "--channel", CHANNEL_ID, "--reply-to", str(event["id"]), "--content", "-"]
    if HUMAN_PUBKEY:
        args.extend(["--mention", HUMAN_PUBKEY])
    buzz(args, input_text=text[:3500])


def reply_with_error(event: dict[str, Any], error: Exception) -> None:
    text = (
        "Pi bridge reached your Buzz message, but the Pi runner call failed.\n\n"
        f"Error: {str(error)[:1000]}"
    )
    buzz(["messages", "send", "--channel", CHANNEL_ID, "--reply-to", str(event["id"]), "--content", "-"], input_text=text)


def fetch_messages(state: dict[str, Any]) -> list[dict[str, Any]]:
    args = ["messages", "get", "--channel", CHANNEL_ID, "--limit", "50"]
    if int(state.get("last_ts") or 0):
        args.extend(["--since", str(int(state["last_ts"]))])
    messages = buzz(args)
    if not isinstance(messages, list):
        return []
    return sorted((item for item in messages if isinstance(item, dict)), key=lambda item: (int(item.get("created_at") or 0), str(item.get("id") or "")))


def seed_history() -> None:
    state = load_state()
    if state.get("last_ts"):
        return
    messages = buzz(["messages", "get", "--channel", CHANNEL_ID, "--limit", "50"])
    if isinstance(messages, list) and messages:
        state["last_ts"] = max(int(item.get("created_at") or 0) for item in messages if isinstance(item, dict))
        state["seen"] = [str(item.get("id")) for item in messages if isinstance(item, dict) and item.get("id")][-500:]
    else:
        state["last_ts"] = int(time.time())
    save_state(state)
    log(f"pi-learning bridge seeded at ts={state['last_ts']}")


def main() -> int:
    log(f"pi-learning bridge starting for channel={CHANNEL_ID} runner={RUNNER_URL}")
    seed_history()
    while True:
        state = load_state()
        seen = set(state.get("seen") or [])
        try:
            for event in fetch_messages(state):
                event_id = str(event.get("id") or "")
                created_at = int(event.get("created_at") or 0)
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                state["seen"] = list(seen)[-500:]
                state["last_ts"] = max(int(state.get("last_ts") or 0), created_at)
                save_state(state)

                if int(event.get("kind") or 0) != 9:
                    continue
                if str(event.get("pubkey") or "").lower() == SELF_PUBKEY:
                    continue
                if HUMAN_PUBKEY and str(event.get("pubkey") or "").lower() != HUMAN_PUBKEY:
                    continue
                if not event_mentions_self(event):
                    continue

                prompt = strip_visible_mention(str(event.get("content") or ""))
                log(f"pi-learning handling event={event_id[:12]}")
                try:
                    response = pi_run_for_message(event, prompt)
                    reply_to_event(event, response)
                    log(f"pi-learning replied to event={event_id[:12]}")
                except Exception as exc:
                    log(f"pi-learning failed event={event_id[:12]}: {exc}")
                    reply_with_error(event, exc)
        except Exception as exc:
            log(f"pi-learning poll failed: {exc}")
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
