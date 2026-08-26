# Task 6 Report: End-To-End Coordination And Loop Safety

## Status

`DONE after final fix` (initial live run was `BLOCKED`)

The automated suites, public readiness/roster checks, bounded phase counts,
quiet window, unrelated-traffic negative test, Desktop restart, typed mention
resolution, and short post-restart task all passed. The prescribed three-worker
root task exposed two protocol defects: Codex's reply used the human root as its
immediate `e` reply tag instead of the Codex ask event, and the final synthesis
did not explicitly identify Codex as the timed-out worker. No source,
configuration, allowlist, backend service, or tracked file was changed, and no
commit was created.

## Secret-handling boundary

All authenticated CLI operations loaded the existing human private key into the
child process environment from the local identity file. The value was never
printed, logged, copied into this report, or passed as a command-line argument.
Only event IDs, public keys, UUIDs, public tags, roles, statuses, and sanitized
phase/semantic summaries are recorded below.

## Automated verification

Commands (run once before live traffic and rerun fresh at the end):

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/pi-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/codex-acp/tests -p 'test_*.py' -v
node --test .runtime/local-buzz-hermes/orchestrator-acp/tests/test_publish_agent_profile.mjs
```

Fresh final results:

```text
orchestrator: Ran 22 tests in 0.008s; OK
pi:           Ran 19 tests in 0.016s; OK
codex:        Ran 6 tests in 0.006s; OK
profile:      4 tests, 4 pass, 0 fail
total:        51 tests, 51 pass, 0 fail
```

## Readiness, services, channel, and roster

Commands:

```bash
curl -sS -o /dev/null -w 'HTTP %{http_code}\n' http://127.0.0.1:38080/_readiness
docker ps --format '{{.Names}}\t{{.Status}}' | sort
BUZZ_PRIVATE_KEY=<loaded privately> buzz --relay http://buzz.localtest.me:3300 \
  channels get --channel 0426f95d-3339-42df-9592-837b3b5506da
BUZZ_PRIVATE_KEY=<loaded privately> buzz --relay http://buzz.localtest.me:3300 \
  channels members --channel 0426f95d-3339-42df-9592-837b3b5506da
```

Result: readiness was `HTTP 200`. The four required learning processes were
running at the start and remained running at the end:

```text
learning-orchestrator-chat-acp  Up 17 minutes
learning-codex-chat-acp         Up 17 minutes
learning-pi-chat-acp-poller     Up 17 minutes
learning-hermes                 Up 17 minutes
```

The active channel was exactly `AI Engineering Lab`
(`0426f95d-3339-42df-9592-837b3b5506da`) with this exact five-member roster:

```text
06add6e5c220ccf02a4456db188bc5ed3e740b0c4eab701d9285f0281c1c1daf  owner  human
a8c43c699d42604c1028863b0835b89e110c22c0a274442d75e1c70489ff1064  bot    orchestrator-chat
2d510a2de07d84948c6447c839de891bf4ce9347f58c946910f2fa517a3840f8  bot    hermes-learning
f0c2b4f8bb5a5ab5627cc469eae194c363e1c142279c0131257c70050259e33d  bot    pi-chat
a7db979b7fc10034961c2488c18a3d50493e085c4256bb0e075594c942ac67f9  bot    codex-chat
```

The first attempt used `http://127.0.0.1:3300` and returned the public error
`404: no community is configured for this host`. Investigation found that Buzz
selects the community from the Host header; all runtime Compose/launcher paths
use `buzz.localtest.me:3300`. Retrying the read-only lookup through that existing
configured hostname succeeded. No config was changed.

## Prescribed human root task

The exact outbound content was:

```text
@orchestrator-chat explain how Buzz ACP agents work and ask Hermes, Pi, and Codex for their views
```

Command shape:

```bash
BUZZ_PRIVATE_KEY=<loaded privately> buzz --relay http://buzz.localtest.me:3300 \
  messages send --channel 0426f95d-3339-42df-9592-837b3b5506da \
  --content '<exact text above>' \
  --mention a8c43c699d42604c1028863b0835b89e110c22c0a274442d75e1c70489ff1064
```

Public send result:

```text
event_id:        49d7285e7ae9cbc45c99f1b0921436866a46c01c06d6e0abd5f78a0f9db61c96
mention_pubkeys: [a8c43c699d42604c1028863b0835b89e110c22c0a274442d75e1c70489ff1064]
```

The orchestrator pubkey was therefore present as a real `p` tag.

## Root-thread protocol and correlations

The thread was polled only through:

```bash
buzz messages thread \
  --channel 0426f95d-3339-42df-9592-837b3b5506da \
  --event 49d7285e7ae9cbc45c99f1b0921436866a46c01c06d6e0abd5f78a0f9db61c96 \
  --limit 100 --depth-limit 10
```

The synthesis arrived 108 seconds after the root, within the 150-second cap.
Final cardinalities were exact: one `[TASK]`, one `[ASK:HERMES]`, one
`[ASK:PI]`, one `[ASK:CODEX]`, and one `[SYNTHESIS]`.

| Phase | Event ID | Author | Immediate reply `e` | Worker `p` |
|---|---|---|---|---|
| root | `49d7285e7ae9cbc45c99f1b0921436866a46c01c06d6e0abd5f78a0f9db61c96` | human | none | orchestrator |
| `[TASK]` | `b12a0382acbfaf76c4e18e7b42c76f237f25d87366075e59e906119b47bf5f14` | orchestrator | root | none |
| `[ASK:HERMES]` | `4c61a6ca14fd2d262565252883387f42ddb87319bac56de17eec815bbe9e0abb` | orchestrator | root | Hermes |
| `[ASK:PI]` | `ea166e1dde5164a04b6a63b1e7689c3606065bc07b18f36f0884b927918acbf8` | orchestrator | root | Pi |
| `[ASK:CODEX]` | `df4f2d2925babc80c097ce35eca06765358faf02774bfe335a4f4e1b668e7d56` | orchestrator | root | Codex |
| Hermes reply | `e13ea9a6d4ee46f100891b8d2876e0c616dee0896aedacfe0c03044ce95571b6` | Hermes | Hermes ask | none |
| Pi reply | `55aed7f261252b237bd4caa651116c3e156e09808d26bf4357c66e8dd4ec0c4f` | Pi | Pi ask | none |
| Codex reply | `6598fdf9bf02f93ed5cb4696f6e253aca7c511688a9792a044f899fddbb9b213` | Codex | **human root (defect)** | none |
| `[SYNTHESIS]` | `1befcf7d6b853da0f5bee55964cb901e8adca649cb4e96ecb499a3b3145ca41d` | orchestrator | root | none |

All three asks carried exactly their intended worker p-tag, and all worker
authors matched their configured public keys. Hermes and Pi correlated
correctly. Codex did not: its immediate reply tag was the root event, not
`df4f2d...`, so `find_contribution` correctly rejected it and the orchestrator
waited through the 90-second collection deadline.

The single synthesis was authored by the orchestrator and rooted correctly. A
sanitized semantic check found general references to Hermes, Pi, and Codex plus
generic engineering timeout/check language, but no clause that identified
Codex as missing or timed out. Its only Codex context described provider/runtime
inference rather than a timed-out contribution. This fails the requirement that
the synthesis explicitly name every timed-out worker.

## Root cause and scoped fixes (not applied)

The live Codex tag matches the existing code path:

- Buzz ACP's `resolve_reply_anchor` flattens a thread reply to the human root
  when the triggering sender is classified as human/unknown.
- That classification is derived solely from a four-element NIP-OA `auth` tag
  on the sender's kind:0 profile; unknown/missing authentication is deliberately
  treated as human.
- Task 4 published the orchestrator kind:0 profile via `buzz users set-profile`,
  whose public CLI supports only name/avatar/about/nip05, and separately
  published a kind:10100 directory profile. The kind:10100 object is not used by
  Buzz ACP's `profile_event_is_agent` routing heuristic.
- `codex_acp_adapter.extract_buzz_routing` prefers any prompt
  `--reply-to <id>` instruction over the current `Event ID`. The resulting
  flattened root anchor therefore won over the Codex ask ID.

Proposed scoped fix: add a regression fixture containing an agent ask event ID
plus a different flattened root instruction, then either (a) publish a valid
NIP-OA-owned kind:0 profile for orchestrator so Buzz ACP classifies the turn as
agent-to-agent, or (b) have the Codex adapter select the current event ID for an
authenticated/configured orchestrator `[ASK:CODEX]` turn while retaining root
flattening for human-facing conversation. Verify the fix with a new live thread
before accepting either option.

Separately, timeout attribution is currently prompt-only: the synthesis prompt
contains `Timed out workers: codex`, but model output is not constrained to
repeat it. Proposed scoped fix: deterministically append/render
`Timed out workers: <names>.` in the published synthesis whenever the list is
non-empty, with an orchestration-level regression test that inspects the final
Buzz send content rather than only the model prompt.

## Loop-prevention quiet window

After observing the synthesis, the root thread was fetched, held for exactly 20
seconds, and fetched again. The phase-event IDs before and after were identical:

```text
1befcf7d6b853da0f5bee55964cb901e8adca649cb4e96ecb499a3b3145ca41d
4c61a6ca14fd2d262565252883387f42ddb87319bac56de17eec815bbe9e0abb
df4f2d2925babc80c097ce35eca06765358faf02774bfe335a4f4e1b668e7d56
ea166e1dde5164a04b6a63b1e7689c3606065bc07b18f36f0884b927918acbf8
```

There were zero new ask/synthesis IDs; phase counts remained
`TASK=1, HERMES=1, PI=1, CODEX=1, SYNTHESIS=1`; no worker message p-tagged any
worker; and no orchestrator reply treated a worker contribution as a fresh task.

## Unrelated-traffic negative test

One ordinary unmentioned top-level message was sent:

```text
Task 6 negative control: ordinary unmentioned human message.
```

Public result:

```text
event_id:        27ca338434dfd7335b7c6cd146d779151df34698f691791e2a9f2b2bff92a806
mention_pubkeys: []
```

After exactly 15 seconds, its thread count remained one (the root only), and
there were zero orchestrator-authored replies with an `e` tag referencing that
event.

## Buzz Desktop restart and typed-name evidence

The installed `/Applications/Buzz.app` (`xyz.block.buzz.app`, version `0.5.17`)
was restarted without deleting or modifying app data:

```text
before PID: 71930
quit status: stopped
after PID:  74136
restart status: new process
```

Direct UI automation was unavailable. The in-app control surface returned
`No browser is available`, and macOS System Events returned `osascript is not
allowed assistive access`. Consequently, this run cannot directly assert that
the visible autocomplete dropdown appeared inside Buzz Desktop.

The strongest available public/functional evidence after restart was positive:

1. `buzz users get --name orchestrator-chat` returned exactly one profile:
   pubkey `a8c43c...`, name/display name `orchestrator-chat`, about text
   `Local Buzz coordinator for Hermes, Pi, and Codex learning`.
2. The short task was sent with typed content only and **without** `--mention`:

   ```text
   @orchestrator-chat explain Buzz ACP in one sentence
   ```

3. Buzz resolved the name into the exact orchestrator p-tag and returned root
   event `fe7efc71f6194d0ae10083084aa70f6dfae386a89d0081541ae2f89a31e98ee1`.
4. The resulting five-event thread was normal and non-timeout:
   `[TASK]` `fb2f8060...` -> root; `[ASK:HERMES]` `b0c4c38b...` -> root with
   Hermes p-tag; Hermes reply `0ee35495...` -> ask; one `[SYNTHESIS]`
   `aa47573b...` -> root; no Pi/Codex asks; synthesis contained no timeout.

This proves public directory resolution and typed-mention delivery survived the
Desktop restart, while the visual autocomplete assertion remains an explicit
automation limitation.

## Final tracked-state and process check

Commands:

```bash
git status --short
docker ps --format '{{.Names}}\t{{.Status}}' | sort
```

Result: `git status --short` produced no output. The full final Docker list was:

```text
learning-buzz-community-proxy  Up 6 days
learning-buzz-minio            Up 7 days (healthy)
learning-buzz-pairing          Up 7 days
learning-buzz-postgres         Up 7 days (healthy)
learning-buzz-redis            Up 7 days (healthy)
learning-buzz-relay            Up 6 days (healthy)
learning-codex-chat-acp        Up 17 minutes
learning-hermes                Up 17 minutes
learning-orchestrator-chat-acp Up 17 minutes
learning-pi-bridge             Up 6 days
learning-pi-chat-acp-poller    Up 17 minutes
learning-pi-runner             Up 6 days (healthy)
```

Transport paths exercised:

```text
human/Buzz CLI -> Buzz relay -> buzz-acp -> orchestrator ACP -> worker adapters -> Buzz relay
Buzz Desktop restart -> persisted human app state -> public Buzz directory/typed name resolution
```

No `subscribe=all`, allowlist change, backend-service restart, data clearing,
implementation change, tracked change, Git commit, or extra mention was used.
Exactly the prescribed root task, one unmentioned negative control, and one
short typed-name task were sent.

---

## Fix round: Codex correlation and deterministic timeout attribution

This section records the scoped fix performed after the initial failure above.
The original failed event graph, root-cause evidence, and Desktop limitation are
preserved unchanged as regression history.

### Scope and files

Only these ignored runtime implementation/test files changed:

```text
.runtime/local-buzz-hermes/codex-acp/codex_acp_adapter.py
.runtime/local-buzz-hermes/codex-acp/tests/test_codex_acp_adapter.py
.runtime/local-buzz-hermes/compose.codex-acp.yml
.runtime/local-buzz-hermes/orchestrator-acp/orchestrator_acp_adapter.py
.runtime/local-buzz-hermes/orchestrator-acp/tests/test_orchestrator_acp_adapter.py
```

No tracked file, allowlist, strict correlation rule, mention gate, loop guard,
backend service, protected service, or secret was changed. No commit was made.

### RED 1: authenticated orchestrator Codex routing

Before production edits, four focused real-function fixtures were added:

- a valid configured orchestrator `[ASK:CODEX]` with a current ask ID and a
  different flattened root must select the current ask ID;
- the same content from a different author must retain the flattened root;
- an ordinary human-thread prompt must retain the flattened root;
- an invalid configured orchestrator key must retain the flattened root.

Command:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/codex-acp/tests -p 'test_*.py' -v
```

Observed RED:

```text
Ran 10 tests in 0.003s
FAILED (failures=1)
test_orchestrator_codex_ask_prefers_current_event_over_flattened_root: FAIL
actual reply target:   cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
expected current ask:  bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
different-author, human-thread, and invalid-key preservation cases: PASS
```

Minimal implementation:

- parse only the current `[Buzz event: ...]` block;
- require `CODEX_ACP_ORCHESTRATOR_PUBKEY` to be valid 64-hex;
- require the current event author to equal that configured key;
- require `[ASK:CODEX]` in the current event block;
- only then prefer the current `Event ID`; otherwise keep the prior flattened
  `--reply-to` precedence;
- wire `CODEX_ACP_ORCHESTRATOR_PUBKEY: ${ORCHESTRATOR_CHAT_PUBKEY}` into the
  Codex service.

Focused GREEN:

```text
Ran 10 tests in 0.003s
OK
```

### RED 2: deterministic timeout attribution

Before the orchestrator production edit, two orchestration-level tests used the
real orchestration flow while replacing only external collection/model work:

- model output omitting timeout attribution must publish exactly one final line
  `Timed out workers: pi, codex.`;
- model output already containing that exact line must not duplicate it.

Command:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_*.py' -v
```

Observed RED:

```text
Ran 24 tests in 0.008s
FAILED (failures=1)
test_orchestration_appends_one_exact_timeout_attribution: FAIL
actual final synthesis omitted: Timed out workers: pi, codex.
pre-attributed no-duplication case: PASS
```

Minimal implementation added `ensure_timeout_attribution(answer, timed_out)`,
which leaves no-timeout output unchanged, removes exact duplicate attribution
lines, and appends one canonical comma-separated line when timeouts exist. The
all-timeout fallback now emits its status sentence separately and relies on the
same canonical line.

The first GREEN attempt correctly passed both new cases but exposed one old
exact-string expectation for the all-timeout fallback (`23/24`). Systematic
inspection showed that the old expectation embedded attribution mid-sentence,
which conflicted with the new required standalone line. The fallback and its
behavioral expectation were aligned to:

```text
No worker contributions arrived before the 90-second deadline.
Timed out workers: hermes.
```

Focused final GREEN:

```text
Ran 24 tests in 0.007s
OK
```

### Full automated GREEN

Fresh final commands:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/pi-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/codex-acp/tests -p 'test_*.py' -v
node --test .runtime/local-buzz-hermes/orchestrator-acp/tests/test_publish_agent_profile.mjs
```

Results:

```text
orchestrator: 24/24 pass
Pi:           19/19 pass
Codex:        10/10 pass
profile:       4/4 pass
total:        57/57 pass, 0 fail
```

Both affected Compose files also passed `docker compose ... config --quiet`.

### Narrow service recreation and protected identities

Only these commands were used for runtime recreation:

```bash
docker compose -f .runtime/local-buzz-hermes/compose.codex-acp.yml \
  up -d --no-deps --force-recreate codex-chat-acp
docker compose -f .runtime/local-buzz-hermes/compose.orchestrator-acp.yml \
  up -d --no-deps --force-recreate orchestrator-chat-acp
```

Affected IDs changed as intended:

```text
learning-codex-chat-acp:        83a1aaa7de09 -> 27ecd47c77ac
learning-orchestrator-chat-acp: 766ccfbb0090 -> 6e627c1b1357
```

The Codex container exposed a syntactically valid public
`CODEX_ACP_ORCHESTRATOR_PUBKEY`; its value was not dumped. All protected IDs
and states were identical before and after:

```text
learning-buzz-relay          45fc55d47fe4  running healthy
learning-hermes              8f453cd36ad9  running
learning-pi-runner           3698d3197b0a  running healthy
learning-pi-chat-acp-poller  f9f26158d478  running
learning-pi-chat-acp         a5c981147abd  stopped (unchanged official websocket service)
```

Buzz readiness remained HTTP 200.

### Fresh fixed live task

Exactly one new prescribed root task was sent with the explicit orchestrator
p-tag:

```text
@orchestrator-chat explain how Buzz ACP agents work and ask Hermes, Pi, and Codex for their views
```

Public send result:

```text
root event:       cb1444b64feb5c976dd7dd63ac65d52d5f30d910e15c9c8f47cc751c96182a30
mention pubkey:   a8c43c699d42604c1028863b0835b89e110c22c0a274442d75e1c70489ff1064
```

The synthesis arrived in 36 seconds. Final cardinalities were exactly one
`[TASK]`, one ask per worker, and one `[SYNTHESIS]`:

| Phase | Event ID | Author | Immediate reply `e` | Worker `p` |
|---|---|---|---|---|
| root | `cb1444b64feb5c976dd7dd63ac65d52d5f30d910e15c9c8f47cc751c96182a30` | human | none | orchestrator |
| `[TASK]` | `aa807827e1870de388bda8ffdfed11ae1f71adca8eb7f9eb06c3a1f33d4c080b` | orchestrator | root | none |
| `[ASK:HERMES]` | `ecc70f27bd4541db87313860d5d8e26f95151d5f3fc2e8b3de64a38307c9be11` | orchestrator | root | Hermes |
| `[ASK:PI]` | `56008fcaef1f1f39ebe03e971b6b64c68e90beac84d3e6c0bfe4a7e2c17da0bb` | orchestrator | root | Pi |
| `[ASK:CODEX]` | `aafd15fd480ee12a92e5f1f8aa3cf2ebe0bd5e64e528e6f9c2c76f60e90ff170` | orchestrator | root | Codex |
| Hermes reply | `0b48c8a55a104114038d89c4b9e5529cb555c569daef671e3937f6552d80775b` | Hermes | Hermes ask | none |
| Pi reply | `ea23b1a9ac7dd4334ee77214cf67c77b68d4a4d7b99f5dc8a96fdd7c94f88ba4` | Pi | Pi ask | none |
| Codex reply | `2a137f3749dbb82c38dda9427da94a5ca086d1ebc343a8bffe393b35c8338b74` | Codex | **Codex ask** | none |
| `[SYNTHESIS]` | `b7331872f1edeb3ce85e473b6fce4a1683336500559f479dbe34034e574d4084` | orchestrator | root | none |

All three authors and immediate correlations matched exactly. The synthesis
named Hermes, Pi, and Codex, contained zero `Timed out workers:` lines, and no
worker timed out.

### Fresh loop and unrelated-traffic checks

For the required 20-second quiet window, the five phase-event IDs before and
after were identical (`TASK`, three asks, synthesis), with no new phase IDs and
no worker cross-p-tags. Cardinalities stayed `1/1/1/1/1`.

One new unmentioned message was then sent:

```text
Task 6 fix negative control: ordinary unmentioned human message.
event_id: eedb888b07351220b97cd039ebfca37104df53be30033a9ed5e3eef1bed7dcdd
mention_pubkeys: []
```

After 15 seconds its thread remained root-only (`thread_count=1`) with zero
orchestrator replies.

### Fix-round final state

```text
status: DONE
automated tests: 57/57 pass
live three-worker correlation: 3/3 exact ask replies
phase cardinalities: TASK=1, ASK:HERMES=1, ASK:PI=1, ASK:CODEX=1, SYNTHESIS=1
timed-out workers: none
quiet window: pass
unmentioned negative check: pass
Buzz readiness: HTTP 200
tracked changes: none
commit: none
```

## Fix round 2: structural ACP parsing and bounded publication

This section preserves the original failure and first fix-round evidence above
and records the bounded second review round. The implementation changes remain
inside ignored local runtime state; no commit or tracked edit was made.

### Reference boundary and diagnosed causes

The full relevant implementations were read before edits:

```text
.runtime/vendor/buzz/crates/buzz-acp/src/queue.rs:1119-1175
.runtime/vendor/buzz/crates/buzz-acp/src/queue.rs:1568-1705
.runtime/vendor/buzz/crates/buzz-acp/src/acp.rs:2043-2055
```

Buzz ACP emits each prompt section as a distinct ACP text block. The round-1
Codex shim flattened those blocks and used an unbounded `rfind` through raw
event content. It therefore trusted injected event-looking text, did not
recognize official multi-event batches, and lost the authoritative block
boundary. Separately, the orchestrator appended timeout attribution before
`BuzzClient.send`, whose generic `content[:3500]` could cut that final line off.

The scoped changes were:

- preserve text blocks for routing while retaining the identical `\n\n` joined
  model prompt;
- accept only an official singular event block or a count-consistent,
  sequential official batch, then parse ID/author from the fixed selected
  record header;
- fail malformed/injected framing closed to the existing flattened root;
- reserve publication space for `[SYNTHESIS]`, a truncated answer body, and one
  canonical final timeout line before reaching the real Buzz send boundary.

### Strict RED evidence

Each regression was introduced and run before its corresponding production
boundary was edited. Focused command shape:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/codex-acp/tests -p 'test_codex_acp_adapter.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_orchestrator_acp_adapter.py' -v
```

Observed RED results:

```text
singular injected event: actual fake injected event ID, expected flattened root
valid two-event batch:   actual flattened root, expected last real event ID
injected batch boundary: actual fake injected event ID, expected flattened root
Codex focused suite:     Ran 13 tests; FAILED (failures=3)

long timeout synthesis:  final subprocess input did not end with the canonical line
orchestrator focused:    Ran 19 tests; FAILED (failures=1)
```

No production edit for either boundary preceded its RED evidence. Focused
GREEN after the bounded changes:

```text
Codex:        Ran 13 tests; OK
orchestrator: Ran 19 tests; OK
```

The long-answer regression uses the real `BuzzClient.send` implementation and
mocks only its external subprocess, collection, and model response. It asserts
the actual subprocess `input` is at most 3,500 characters, ends with
`Timed out workers: pi, codex.`, and contains that exact line once.

### Full automated GREEN

Both the pre-recreation and final fresh runs used:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/pi-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/codex-acp/tests -p 'test_*.py' -v
node --test .runtime/local-buzz-hermes/orchestrator-acp/tests/test_publish_agent_profile.mjs
```

Final fresh results:

```text
orchestrator: 25/25 pass (Ran 25 tests in 0.006s)
Pi:           19/19 pass (Ran 19 tests in 0.006s)
Codex:        13/13 pass (Ran 13 tests in 0.004s)
profile:        4/4 pass
total:         61/61 pass, 0 fail
```

With `.runtime/local-buzz-hermes/state/public.env` loaded privately, both
affected `docker compose ... config --quiet` commands passed. An initial
read-only invocation without that public environment also exited successfully
but reported expected unset-variable warnings; it did not change state.

### Narrow service recreation and protected services

Only the two authorized services were recreated:

```bash
docker compose -f .runtime/local-buzz-hermes/compose.codex-acp.yml up -d --no-deps --force-recreate codex-chat-acp
docker compose -f .runtime/local-buzz-hermes/compose.orchestrator-acp.yml up -d --no-deps --force-recreate orchestrator-chat-acp
```

Affected IDs changed:

```text
learning-codex-chat-acp:        27ecd47c77ac -> 8fbe982a9cda
learning-orchestrator-chat-acp: 6e627c1b1357 -> d67dd782276a
```

Protected IDs and states were unchanged:

```text
learning-buzz-relay          45fc55d47fe4  running healthy
learning-hermes              8f453cd36ad9  running
learning-pi-runner           3698d3197b0a  running healthy
learning-pi-chat-acp-poller  f9f26158d478  running
learning-pi-chat-acp         a5c981147abd  stopped (unchanged official websocket service)
```

Both recreated agents initialized, connected, discovered their expected public
channels, and subscribed in mention mode. Buzz readiness remained HTTP 200.

### Fresh live coordination

Exactly one fresh prescribed root was sent, using the human identity privately
and the explicit orchestrator p-tag:

```text
@orchestrator-chat explain how Buzz ACP agents work and ask Hermes, Pi, and Codex for their views
```

Public send result:

```text
root event:     1674ef8f540015df6999128c86d3bf277d2acbf9e72481d31cff6c62d32d93ae
orchestrator p: a8c43c699d42604c1028863b0835b89e110c22c0a274442d75e1c70489ff1064
```

The synthesis arrived in 34 seconds. Polling was restricted to that root via
`buzz messages thread --event <root>`. Exact public relationships:

| Phase | Event ID | Author pubkey | Immediate reply `e` | Worker `p` |
|---|---|---|---|---|
| root | `1674ef8f540015df6999128c86d3bf277d2acbf9e72481d31cff6c62d32d93ae` | `06add6e5c220ccf02a4456db188bc5ed3e740b0c4eab701d9285f0281c1c1daf` | none | orchestrator |
| `[TASK]` | `06ddd59795ff0a2fec64acb28ce983fbe832a51cfde7a6d349b08103bbc206c0` | orchestrator | root | none |
| `[ASK:HERMES]` | `31a2f3fd35e21dacc8eb01443b026114b509b77b361337c95613deb650045256` | orchestrator | root | `2d510a2de07d84948c6447c839de891bf4ce9347f58c946910f2fa517a3840f8` |
| `[ASK:PI]` | `6ed63e7b36e7f9f05be5724b7b228d7939f058794d8f4e1c33b9afeac2ea0fd0` | orchestrator | root | `f0c2b4f8bb5a5ab5627cc469eae194c363e1c142279c0131257c70050259e33d` |
| `[ASK:CODEX]` | `bb295f83e19b3eb1714245da0f57abb0e0a9ae2dcba8aa29fbdbf649a7aed596` | orchestrator | root | `a7db979b7fc10034961c2488c18a3d50493e085c4256bb0e075594c942ac67f9` |
| Hermes reply | `2c3c6c6c3836f10e50c1397eec6cd5c1b4613cb9d4c4534efcda8a8d90a2bb9d` | `2d510a2de07d84948c6447c839de891bf4ce9347f58c946910f2fa517a3840f8` | Hermes ask | none |
| Pi reply | `c2199a5e8abd7c30b43dd6a4116ce9b2b9ab9868fc40b5c50aa1fed7debe94ed` | `f0c2b4f8bb5a5ab5627cc469eae194c363e1c142279c0131257c70050259e33d` | Pi ask | none |
| Codex reply | `0b870b00b3cb203491fadcba1b8612077c31fa7625e287b423d34bcd3d0f5f5f` | `a7db979b7fc10034961c2488c18a3d50493e085c4256bb0e075594c942ac67f9` | **Codex ask** | none |
| `[SYNTHESIS]` | `d23a18114d0e0a0847eac5e71be1367dcc39e9ef6f0c2c6cca9bcaa5935464d3` | orchestrator | root | none |

Cardinalities were exactly `TASK=1`, `ASK:HERMES=1`, `ASK:PI=1`,
`ASK:CODEX=1`, `SYNTHESIS=1`; all three worker authors and immediate reply
correlations matched. The synthesis had zero timeout lines because all three
contributions arrived.

### Quiet and unmentioned negative windows

After 20 seconds, the thread still contained nine events and the exact same
five phase IDs shown above. There were no new phases, worker cross-p-tags, or
orchestrator reactions to contributions as fresh tasks.

The sole round-2 negative message was unmentioned:

```text
Task 6 fix round 2 negative control: ordinary unmentioned human message.
event_id: 50f624f613e6874faec91486893c3653037f6706fd22ffc7cfa4ae66b7dc7aba
mention_pubkeys: []
```

After 15 seconds, its thread count remained one and there were zero
orchestrator-authored replies.

### Fix-round-2 final state

```text
status: DONE
automated tests: 61/61 pass
live three-worker correlation: 3/3 exact ask replies
phase cardinalities: TASK=1, ASK:HERMES=1, ASK:PI=1, ASK:CODEX=1, SYNTHESIS=1
timed-out workers: none
quiet window: pass
unmentioned negative check: pass
Buzz readiness: HTTP 200
tracked changes: none
commit: none
concerns: none
```

## Final fix: Buzz CLI failure containment

The final whole-runtime review found that a sanitized `RuntimeError` from
`BuzzClient.get()` escaped collection after TASK/ASK publication, leaving no
SYNTHESIS. It also confirmed that `BuzzClient.send()` lacked a subprocess
timeout and that valid non-object JSON could terminate the ACP request loop.
This section records the bounded final fix; no unrelated runtime behavior was
changed.

### Strict RED evidence

The four regressions were added one at a time and observed failing before any
production edit. Focused command:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_orchestrator_acp_adapter.py' -v
```

Observed RED outcomes:

```text
send timeout:         subprocess timeout was None, expected configured 1.25
collection failure:   sanitized RuntimeError escaped instead of reaching deadline
orchestration path:   RuntimeError escaped after TASK/ASK, before SYNTHESIS
non-object ACP input: array caused .get() AttributeError and terminated run()
focused suite:        Ran 23 tests; FAILED (failures=4)
```

The root causes were localized: `send()` omitted the same configured timeout
already used by `get()`; collection caught only `TimeoutExpired`; and the ACP
exception path called `.get()` on the decoded value without first proving it
was an object.

The scoped production changes were:

- pass `ORCHESTRATOR_BUZZ_TIMEOUT_SECS` (default 30 seconds) to the real send
  subprocess;
- treat `TimeoutExpired` and sanitized `RuntimeError` only around the
  `buzz.get(...)` boundary as empty polls, retaining the single absolute
  deadline and capped sleep;
- reject arrays/scalars with JSON-RPC code `-32600` and null ID, while storing
  request IDs separately so the exception handler never dereferences a
  non-object.

The real orchestration regression uses a one-worker fake Buzz boundary and
injects only clock/sleeper defaults. After controlled read failures it observes
TASK and ASK followed by exactly one deterministic SYNTHESIS, with the worker
named as timed out and no raw error detail in the published message.

Focused GREEN:

```text
Ran 23 tests in 0.006s
OK
```

### Full automated and configuration GREEN

Fresh full commands:

```bash
python3 -m unittest discover -s .runtime/local-buzz-hermes/orchestrator-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/pi-acp/tests -p 'test_*.py' -v
python3 -m unittest discover -s .runtime/local-buzz-hermes/codex-acp/tests -p 'test_*.py' -v
node --test .runtime/local-buzz-hermes/orchestrator-acp/tests/test_publish_agent_profile.mjs
```

Results:

```text
orchestrator: 29/29 pass (Ran 29 tests in 0.006s)
Pi:           19/19 pass (Ran 19 tests in 0.013s)
Codex:        13/13 pass (Ran 13 tests in 0.006s)
profile:        4/4 pass
total:         65/65 pass, 0 fail
```

With public runtime variables loaded privately, both Codex and orchestrator
Compose files passed `docker compose ... config --quiet`.

### Orchestrator-only recreation and read-only live validation

Only this service was recreated:

```text
learning-orchestrator-chat-acp: d67dd782276a -> 41c8a5f9ca38
```

All protected IDs/states remained unchanged:

```text
learning-buzz-relay          45fc55d47fe4  running healthy
learning-codex-chat-acp      8fbe982a9cda  running
learning-hermes              8f453cd36ad9  running
learning-pi-runner           3698d3197b0a  running healthy
learning-pi-chat-acp-poller  f9f26158d478  running
learning-pi-chat-acp         a5c981147abd  stopped (unchanged official websocket service)
```

The recreated orchestrator initialized, connected, subscribed to the existing
AI Engineering Lab channel in mention mode, and Buzz readiness was HTTP 200.
No new live messages were sent.

The established latest root
`1674ef8f540015df6999128c86d3bf277d2acbf9e72481d31cff6c62d32d93ae`
was read again. It remained exactly nine events: root, one TASK, one ask for
each worker, three worker replies, and one SYNTHESIS. The existing immediate
correlations remained exact:

```text
Hermes ask 31a2f3fd...4256 -> reply 2c3c6c6c...bb9d
Pi ask     6ed63e7b...0fd0 -> reply c2199a5e...94ed
Codex ask  bb295f83...d596 -> reply 0b870b00...f5f5f
```

### Final-fix state

```text
status: DONE
automated tests: 65/65 pass
focused adapter tests: 23/23 pass
existing live graph: 9 events, 3/3 exact worker correlations
new live traffic: none
Buzz readiness: HTTP 200
tracked changes: none
commit: none
remaining blocking findings: none
non-blocking documented minors: publisher auth wait, Pi display/sequential behavior, Desktop visual autocomplete
```
