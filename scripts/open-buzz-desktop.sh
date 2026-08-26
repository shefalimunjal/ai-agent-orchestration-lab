#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HUMAN_IDENTITY_JSON="${HUMAN_IDENTITY_JSON:-$ROOT_DIR/runtime/identities/human.json}"
DESKTOP_DIR="${BUZZ_DESKTOP_DIR:-$ROOT_DIR/../workpods-umbrella/.runtime/vendor/buzz/desktop}"

if [[ -d /opt/homebrew/opt/rustup/bin ]]; then
  export PATH="/opt/homebrew/opt/rustup/bin:$PATH"
fi

if [[ ! -f "$HUMAN_IDENTITY_JSON" ]]; then
  echo "Missing learning identity: $HUMAN_IDENTITY_JSON" >&2
  exit 1
fi

if [[ ! -d "$DESKTOP_DIR" ]]; then
  echo "Missing Buzz desktop checkout: $DESKTOP_DIR" >&2
  exit 1
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required to read the local identity file." >&2
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "pnpm is not installed or not on PATH." >&2
  echo "Try: corepack enable && corepack prepare pnpm@latest --activate" >&2
  exit 1
fi

if ! command -v cargo >/dev/null 2>&1; then
  echo "Rust/Cargo is required for the Tauri desktop app." >&2
  echo "Install Rust, then rerun this script." >&2
  exit 1
fi

export BUZZ_PRIVATE_KEY
BUZZ_PRIVATE_KEY="$(jq -r '.private_key' "$HUMAN_IDENTITY_JSON")"

export BUZZ_RELAY_URL="ws://buzz.localtest.me:3300"

cd "$DESKTOP_DIR"
exec pnpm tauri dev
