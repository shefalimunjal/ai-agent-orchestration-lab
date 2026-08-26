# WorkPods Buzz AI Agents Lab

Local-only lab for connecting three conversational agents to Buzz and coordinating them through an orchestrator:

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

This repo assumes the WorkPods repos live as siblings under the same parent directory:

```text
AI-Labs/
  workpods-buzz-ai-agents-lab/
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
