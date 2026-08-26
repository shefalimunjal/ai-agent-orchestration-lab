# AI Agent Orchestration Lab

Portfolio project demonstrating a local multi-agent AI engineering system: three conversational agents coordinate through a message bus under one orchestrator agent.

- `hermes-learning`: Hermes teaching agent for architecture and concepts.
- `pi-chat`: Pi ACP conversational agent for workflow, harness, and runner boundaries.
- `codex-chat`: Codex ACP conversational agent for code, debugging, and verification.
- `orchestrator-chat`: Buzz coordinator that delegates one user task to Hermes, Pi, and Codex, then posts one synthesis.

This repository is a sanitized extraction of the local Buzz integration work. It intentionally excludes identity JSON, Codex auth JSON, SQLite state, logs, generated sessions, and secret env files.

## Layout

- `agents/orchestrator-acp`: orchestration logic, ACP adapter, profile publisher, and tests.
- `adapters/codex-acp`: Buzz ACP to Codex CLI bridge.
- `adapters/pi-acp`: Buzz ACP to Pi bridge plus the polling fallback used in the lab.
- `bridges/pi`: earlier workflow-harness bridge for `pi-learning`.
- `compose`: Docker Compose files for Buzz, Hermes, Pi, Codex, and the orchestrator.
- `examples/runtime`: templates for ignored runtime env files.
- `docs`: design, implementation plan, and verification report.

## Runtime Model

Buzz is the shared message bus. Each conversational worker listens to Buzz and replies only when mentioned or when the orchestrator asks it directly.

```text
Human in Buzz
  -> @orchestrator-chat
  -> [TASK]
  -> [ASK:HERMES] / [ASK:PI] / [ASK:CODEX]
  -> worker replies
  -> [SYNTHESIS]
```

The current setup is a learning coordinator. It asks the agents for analysis and synthesis; it does not let them modify repositories or commit code.

## Local Setup Notes

This lab was developed against the local WorkPods/Buzz source tree. By default, it assumes those repos live as siblings under the same parent directory:

```text
AI-Labs/
  ai-agent-orchestration-lab/
  workpods-umbrella/
  workpods-buzz/
  workpods-ingest/
```

If your paths differ, set these env vars before running Compose:

```bash
export WORKPODS_BUZZ_DIR=/path/to/workpods-buzz
export WORKPODS_INGEST_DIR=/path/to/workpods-ingest
export WORKPODS_WORKSPACE_DIR=/path/to/workpods-umbrella
```

Create runtime files from the examples, then fill them with local-only generated keys and secrets:

```bash
mkdir -p runtime/{identities,codex-acp,pi-acp,pi/secrets,hermes/secrets}
cp examples/runtime/buzz.env.example runtime/buzz.env
cp examples/runtime/codex-chat-acp.env.example runtime/codex-acp/codex-chat-acp.env
cp examples/runtime/pi-chat-acp.env.example runtime/pi-acp/pi-chat-acp.env
cp examples/runtime/pi-runner.env.example runtime/pi/secrets/pi-runner.env
cp examples/runtime/pi-bridge.env.example runtime/pi/secrets/pi-bridge.env
cp examples/runtime/hermes-learning.env.example runtime/hermes/secrets/hermes-learning.env
```

You also need:

- `bin/buzz-acp-linux` from the Buzz ACP build.
- `runtime/identities/*.json` generated locally.
- Codex auth JSON copied locally into the ignored runtime Codex homes when using Codex as the provider.

## Private Mobile Access With Tailscale

Tailscale can make the local Buzz community available to a phone without
publishing the relay to the internet. Install Tailscale on the host and phone,
sign both into the same tailnet, and keep Tailscale Funnel disabled.

Use the host's MagicDNS name as one canonical origin in `runtime/buzz.env`:

```dotenv
RELAY_URL=wss://your-machine.your-tailnet.ts.net
BUZZ_PUBLIC_WS_URL=wss://your-machine.your-tailnet.ts.net
BUZZ_PUBLIC_HTTP_URL=https://your-machine.your-tailnet.ts.net
BUZZ_PUBLIC_HOST=your-machine.your-tailnet.ts.net
BUZZ_PAIRING_RELAY_URL=wss://your-machine.your-tailnet.ts.net/pair
```

Pass that file when starting every Compose group so the ACP agents inherit the
same secure relay URL. Hermes and the older Pi bridge use the HTTPS form in
their service-specific env files; the examples already show that form.

Start the Buzz stack, then privately proxy the loopback-only community proxy:

```bash
tailscale serve --bg 3330
tailscale serve status
```

Use this community URL in Buzz Mobile:

```text
https://your-machine.your-tailnet.ts.net
```

Before generating the QR, update the active community's relay URL in Buzz
Desktop to the secure WebSocket form:

```text
wss://your-machine.your-tailnet.ts.net
```

This distinction matters: Desktop connects with `wss://`, then exports the
same community to Mobile as an `https://` base URL. A Desktop community still
using a local `ws://` address produces a credential payload that release
mobile builds correctly reject.

For an existing community originally created as `buzz.localtest.me:3300`,
preserve its community UUID and migrate only its `communities.host` value to
`your-machine.your-tailnet.ts.net`. Verify the selected row before updating
it. Do not create a second community: channel membership and history are tied
to the existing UUID.

This host migration is required by NIP-98. A request made through WSS signs
its HTTP endpoint as `https://your-machine.your-tailnet.ts.net/query`; Buzz
rejects it if the relay configuration, proxy `Host`, or community row still
expects `http://buzz.localtest.me:3300/query`. Changing only the Desktop relay
URL therefore causes a correct `401 Unauthorized` URL-mismatch response.

Next, open **Settings > Mobile > Start pairing**, scan the QR in Buzz Mobile,
and confirm that the six-digit verification code matches on both devices. The
`/pair` route sends encrypted pairing events to the dedicated pairing relay;
the main `/` route continues to serve the Buzz community.

A raw Tailscale `100.x` IP is useful for diagnostics, but the MagicDNS hostname
is the supported community address because its HTTPS/WSS certificate and
`/pair` route work together. The host must remain awake and online with
Tailscale, Docker, Buzz, and the agents running.

## Testing

Install Node dependencies and run the adapter/controller tests:

```bash
npm install
npm test
```

The tests cover the orchestrator selection and synthesis logic, ACP framing, wrong-author and prompt-injection defenses, Pi polling, Codex reply correlation, and profile publishing helpers.

## Using The Lab

Open Buzz Desktop, join the `AI Engineering Lab` community/channel, then send:

```text
@orchestrator-chat ask all three agents to explain ACP and compare their roles
```

For a focused task, mention a worker directly:

```text
@codex-chat explain why the adapter replies to the orchestrator ASK event instead of the human root event
```
