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

## Pairing Outcome

- Buzz Desktop transferred the existing `learning-user` identity through the
  encrypted QR and matching-code pairing flow.
- Buzz Mobile opened the existing `AI Engineering Lab` community and channel;
  it did not create a second identity or community.
- A message sent from the tailnet-connected iPhone reached the relay, triggered
  the configured agents, and produced the expected response in the shared
  channel.
- The relay retained the mobile-authored message and agent replies as ordinary
  channel history, so both clients consume the same event stream.

## Desktop Synchronization Lesson

Desktop initially did not render the mobile-authored events even though the
relay stored them and its channel cache observed the latest activity. The
Desktop process had remained alive across the canonical relay URL migration,
leaving its in-memory timeline subscription stale.

A graceful **Command-Q** followed by relaunch created a fresh TLS connection,
reissued successful history queries, and restored the shared timeline. No
community deletion, local-storage clearing, or second pairing was required.
This distinguishes transport and persistence health from client subscription
state during troubleshooting.

No private keys, identity files, authentication data, runtime database data,
pairing payloads, verification codes, or personal message content are included
in this report.
