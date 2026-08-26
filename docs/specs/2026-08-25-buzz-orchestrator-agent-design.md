# Buzz Orchestrator Agent Design

Date: 2026-08-25

## Goal

Create a local-only learning setup where a new Buzz agent, `orchestrator-chat`, coordinates the three existing Buzz agents:

- `hermes-learning` for architecture explanation, teaching, and conceptual decomposition.
- `pi-chat` for workflow/harness perspective and structured execution framing.
- `codex-chat` for code, repository, implementation, and verification perspective.

The first version should make coordination visible in Buzz so the human can learn how agent collaboration works.

## Non-goals

- Do not create a hidden autonomous system that runs indefinitely.
- Do not make every agent subscribe to every message.
- Do not sync private memory across agents.
- Do not perform destructive repository or machine actions without explicit human approval.
- Do not solve multi-agent scheduling, retries, or parallel execution at production scale.

## Recommended architecture

Add a new conversational ACP-backed Buzz agent:

```text
human
  -> orchestrator-chat
      -> hermes-learning
      -> pi-chat
      -> codex-chat
  -> final synthesis from orchestrator-chat
```

Buzz remains the coordination bus. The orchestrator posts visible tagged messages to the worker agents in a shared coordination channel/thread. Worker agents answer in Buzz. The orchestrator collects those replies and posts a final synthesis.

## Channel model

Create a dedicated channel named `AI Engineering Lab`.

Members:

- human owner
- `orchestrator-chat`
- `hermes-learning`
- `pi-chat`
- `codex-chat`

This keeps experimental multi-agent traffic out of the existing Hermes/Pi/Codex learning channels.

## Agent roles

### `orchestrator-chat`

The coordinator. It receives the human task and controls the collaboration protocol.

Responsibilities:

1. Restate the task.
2. Decide whether the task needs all three workers or only a subset.
3. Ask each selected worker one bounded question.
4. Wait for worker replies.
5. Combine replies into a final answer.
6. Explain which agent contributed what.

### `hermes-learning`

The teacher/architect.

Best for:

- explaining the problem
- identifying concepts and architecture
- clarifying how Buzz/Hermes/ACP/MCP fit together
- suggesting learning paths

### `pi-chat`

The workflow/harness agent.

Best for:

- breaking a task into structured steps
- describing workflow harness behavior
- framing inputs/outputs/contracts
- thinking about bounded execution

### `codex-chat`

The coding/verification agent.

Best for:

- inspecting local repos
- proposing code changes
- explaining implementation details
- suggesting tests and verification steps

## Coordination protocol, v1

The orchestrator should use explicit message phases:

```text
[TASK]
Human request summarized by orchestrator.

[ASK:HERMES]
Architecture/teaching question.

[ASK:PI]
Workflow/harness question.

[ASK:CODEX]
Implementation/repo question.

[SYNTHESIS]
Final combined answer for the human.
```

Each worker request should include:

- the original human task
- the worker's expected role
- a short output format
- a request to avoid directly delegating to other agents

Example worker prompt:

```text
@codex-chat
[ASK:CODEX]
Task: Explain how to add a new Buzz ACP agent.
Your role: implementation/repo perspective.
Return: concise implementation notes, risks, and verification steps.
Do not ask other agents; reply only with your contribution.
```

## Loop prevention

The first version uses strict loop prevention:

- Only `orchestrator-chat` delegates.
- Worker agents do not tag other agents.
- Worker replies are treated as inputs, not new tasks.
- Orchestrator posts only one final synthesis unless the human asks for a follow-up.
- All agents remain mention-triggered where possible.

## Response collection

For the learning version, use a simple bounded collection model:

- Orchestrator sends worker prompts in the channel/thread.
- Orchestrator waits for replies for a fixed local timeout.
- If one worker does not reply, the final synthesis says which worker timed out.
- The orchestrator does not block forever.

Initial timeout: 90 seconds per coordination round.

## Local implementation approach

Implement `orchestrator-chat` as a local ACP-backed Buzz agent similar to `codex-chat`.

Expected local path:

```text
Buzz
  -> buzz-acp
  -> orchestrator-acp shim
  -> local orchestration logic
  -> Buzz messages to workers
  -> Buzz read/poll for replies
  -> final Buzz message
```

The orchestrator can initially be mostly deterministic Python logic with a final synthesis step powered by Codex if needed.

## Why not make Hermes the coordinator?

Hermes would be a natural teacher, but keeping coordination separate makes the learning model clearer:

- Hermes remains one worker with a teaching specialty.
- Pi remains one worker with a harness/workflow specialty.
- Codex remains one worker with an implementation specialty.
- `orchestrator-chat` becomes the explicit example of agent coordination.

## Safety and permissions

The orchestrator should be local-only and allowlisted to the human identity.

For the first version:

- It can send Buzz messages.
- It can read recent messages in the coordination channel.
- It should not edit files directly.
- It should not run shell commands directly.
- It can ask `codex-chat` for implementation guidance instead of doing implementation itself.

This makes the first version safe for learning and easy to reason about.

## Success criteria

The setup is successful when the human can send:

```text
@orchestrator-chat explain how Buzz ACP agents work and ask Hermes, Pi, and Codex for their views
```

And observe:

1. `orchestrator-chat` posts a task summary.
2. It mentions `hermes-learning`, `pi-chat`, and `codex-chat`.
3. Each available worker replies.
4. `orchestrator-chat` posts one final synthesis.
5. No infinite agent loop occurs.

## Testing plan

Manual smoke tests:

1. Verify `orchestrator-chat` is a bot member and mentionable in `AI Engineering Lab`.
2. Send a simple human prompt mentioning `orchestrator-chat`.
3. Confirm the message has a real `p` mention tag.
4. Confirm worker prompts include real mention tags for each worker.
5. Confirm at least one worker response is collected.
6. Confirm final synthesis is posted.
7. Confirm unrelated messages do not trigger the orchestrator.

Automated tests where practical:

- Unit test routing/worker prompt construction.
- Unit test reply collection filters.
- Unit test timeout behavior.
- Unit test loop-prevention rules.

## Open implementation choices

These choices should be made during implementation planning:

1. Whether the orchestrator uses the existing `codex-acp` shim plus prompt rules or a new purpose-built `orchestrator-acp` shim.
2. Whether the final synthesis is deterministic or model-generated.
3. Whether worker prompts are sent sequentially or in parallel.

Recommended defaults:

- Use a purpose-built `orchestrator-acp` shim.
- Use deterministic routing plus Codex-powered final synthesis.
- Send worker prompts in parallel, then collect for a fixed timeout.
