# Buzz Mobile Canonical-Origin Verification

## Problem

Buzz Desktop was changed to the secure Tailscale WebSocket URL, but the relay
still treated `buzz.localtest.me:3300` as the community's canonical host.
NIP-98 rejected signed HTTP requests because the event URL and relay-expected
URL differed.

## Root Cause

The externally signed endpoint used the HTTPS form of the Tailscale origin,
while the relay combined its local scheme and the reverse proxy's rewritten
local `Host`. Pairing transport was available, but authenticated community API
requests failed before credentials could be imported.

## Correction

- Preserved the existing community UUID and migrated only its host.
- Configured the relay, reverse proxy, Desktop, and conversational agents to
  use one canonical Tailscale origin.
- Kept the pairing path on the same private hostname.
- Recreated only services that consume the endpoint configuration.
- Preserved database, Redis, object storage, pairing relay, runner state,
  identities, channels, memberships, and messages.
- Kept the unused Pi WebSocket service stopped.

## Verification

- HTTPS readiness returned `ready`.
- Both the main and `/pair` secure WebSocket handshakes opened.
- NIP-11 advertised the secure `/pair` endpoint.
- A signed channel query using the existing human identity succeeded through
  HTTPS, proving the NIP-98 canonical URL matched.
- The community retained 8 channels, 21 channel memberships, and 7 relay
  members after the in-place host migration.
- Hermes discovered both learning channels through HTTPS.
- Pi, Codex, and the orchestrator reconnected through WSS.
- Persistent container identities were unchanged, and the intentionally
  stopped Pi WebSocket service remained stopped.

No private keys, identity files, authentication data, runtime database data,
or pairing payloads are included in this report.
