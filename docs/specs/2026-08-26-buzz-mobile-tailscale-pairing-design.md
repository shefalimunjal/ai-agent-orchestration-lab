# Buzz Mobile Pairing over Tailscale

## Goal

Pair an iPhone with the existing `learning-user` Buzz identity and connect it
to the local Buzz community from outside the home network. The relay and
pairing service must remain private to the user's Tailscale network.

## Current State

- Buzz runs locally on the Mac in Docker.
- Tailscale Serve exposes the community relay at
  `https://m-dy0xcqpqvv.tail6733e0.ts.net`.
- HTTPS readiness and the main secure WebSocket handshake pass.
- The relay currently advertises `ws://pairing:5000` for mobile pairing. That
  Docker-only hostname is not reachable from the iPhone.

## Selected Design

Use one Tailscale HTTPS hostname for both services:

```text
Buzz Mobile
   |
   +-- community: wss://m-dy0xcqpqvv.tail6733e0.ts.net/
   |
   +-- pairing:   wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair
                            |
                            v
                    Local pairing relay
```

The existing community-aware reverse proxy will route `/` to the Buzz relay
and `/pair` to the dedicated pairing relay. The Buzz relay's NIP-11 document
will advertise the routable, tailnet-only `/pair` WebSocket URL.

## Alternatives Considered

1. Expose pairing on a second HTTPS port. This keeps routing separate but adds
   an endpoint and more mobile configuration.
2. Send pairing events through the main Buzz relay. This removes a service but
   mixes ephemeral device-pairing traffic with community traffic and can
   conflict with relay authentication policy.
3. Use the Mac's raw Tailscale IP as the community URL. This is useful for
   diagnostics but does not match the automatically provisioned TLS
   certificate and does not provide the hostname-based `/pair` routing.

## Configuration Changes

1. Add a WebSocket-capable `/pair` location to the existing Nginx community
   proxy and forward it to the pairing container on port 5000.
2. Configure the Buzz relay to advertise
   `wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair` as its pairing relay URL.
3. Make the Tailscale hostname the canonical relay origin in the relay,
   reverse proxy, existing community row, Desktop, Hermes, Pi, Codex, and the
   orchestrator. WSS clients use `wss://`; signed HTTP API clients use the
   corresponding `https://` origin.
4. Preserve the existing community UUID, channels, memberships, messages,
   identities, and persistent service volumes during the host migration.
5. Recreate the community proxy, Buzz relay, and only the conversational
   clients that need the new endpoint. Keep databases and runner state intact.
6. Keep Tailscale Serve pointed at the loopback-only community proxy.

## Canonical Origin and NIP-98

Buzz verifies NIP-98 requests against an exact URL assembled from the relay
scheme, the community host, and the API path. The externally signed URL and
the relay's expected URL must therefore match byte-for-byte. For this design,
the WebSocket origin `wss://<machine>.<tailnet>.ts.net` maps to the HTTP API
origin `https://<machine>.<tailnet>.ts.net`.

Changing only Buzz Desktop is insufficient. If Nginx rewrites `Host` to
`buzz.localtest.me:3300` or the existing community row retains that local
host, a signed `/query` request correctly fails with `401 Unauthorized` and a
NIP-98 URL mismatch. The reverse proxy must preserve the public host, and the
existing community row must be migrated in place.

## Pairing Flow

1. The user opens Buzz Desktop and selects **Settings > Mobile > Start
   pairing**.
2. Desktop probes the main relay's NIP-11 metadata and embeds the advertised
   `/pair` URL in a short-lived QR code.
3. Buzz Mobile scans the QR and both devices connect to the dedicated pairing
   relay over Tailscale.
4. Both devices display the same six-digit short authentication string (SAS).
5. The user confirms the match on both devices.
6. Desktop transfers the existing Buzz identity through the end-to-end
   encrypted pairing protocol. The raw private key is never manually copied or
   displayed.
7. Mobile stores the identity in platform-secure storage and connects to the
   community relay using secure WebSockets.

## Security Properties

- Tailscale Serve is tailnet-only; Tailscale Funnel remains disabled.
- Docker services remain bound to loopback or the private Docker network.
- Pairing payloads are end-to-end encrypted; the pairing relay only transports
  temporary encrypted events.
- Identity transfer requires an explicit matching-code confirmation on both
  devices.
- No identity files, private keys, authentication files, runtime databases, or
  generated pairing codes are committed.

## Error Handling

- A NIP-11 check must fail if the pairing URL is still Docker-internal.
- The `/pair` WebSocket check must fail closed if the route is unavailable.
- An expired QR code is regenerated from Buzz Desktop.
- A mismatched SAS code cancels pairing; the user must start a new session.
- Existing agent connectivity must be verified after the relay restart.

## Verification

The implementation is complete only when all of the following pass:

1. Docker Compose configuration validation.
2. Main HTTPS readiness through the Tailscale hostname.
3. Main `wss://` WebSocket handshake.
4. `/pair` secure WebSocket handshake.
5. NIP-11 advertises the exact tailnet-only `/pair` URL.
6. A signed `/query` using the existing human identity succeeds through the
   Tailscale HTTPS origin without a NIP-98 mismatch.
7. Hermes, Pi, Codex, and the orchestrator reconnect through the canonical
   Tailscale endpoint.
8. Desktop generates a QR containing the Tailscale pairing endpoint.
9. The iPhone completes SAS confirmation and opens the existing Buzz
   community as `learning-user`.

## Operational Constraint

The Mac must remain powered on with Tailscale, Docker, the Buzz relay, and the
agent containers running. The Tailscale hostname is the supported community
address; the raw `100.107.54.56` address is reserved for network diagnostics.
