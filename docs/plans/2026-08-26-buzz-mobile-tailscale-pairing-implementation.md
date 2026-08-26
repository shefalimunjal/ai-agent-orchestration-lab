# Buzz Mobile Tailscale Pairing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Pair the iPhone with the existing `learning-user` Buzz identity and make the local Buzz community usable from any network through a private Tailscale hostname.

**Architecture:** Tailscale Serve terminates HTTPS/WSS on the Mac and forwards to a loopback-only Nginx community proxy. Nginx routes `/` to the Buzz community relay and `/pair` to the dedicated NIP-AB pairing relay; the main relay advertises the exact tailnet-only `/pair` URL in NIP-11 metadata.

**Tech Stack:** Tailscale Serve and MagicDNS, Docker Compose, Nginx WebSocket reverse proxying, Buzz relay and pairing relay, NIP-11, NIP-AB, Node.js `ws`, Flutter Buzz Mobile.

## Global Constraints

- The phone must reuse the existing `learning-user` Buzz identity.
- The supported community URL is `https://m-dy0xcqpqvv.tail6733e0.ts.net`.
- The pairing URL is `wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair`.
- Tailscale Funnel remains disabled; all access is tailnet-only.
- Docker services remain loopback-only or private to the Docker network.
- Never print, copy into commands, or commit private keys, identity JSON, Codex auth, pairing QR payloads, SAS codes, runtime databases, logs, or full environment files.
- Do not commit runtime changes in `workpods-umbrella`; only sanitized, reusable files belong in `ai-agent-orchestration-lab`.
- Recreate only the Buzz relay and community proxy. Hermes, Pi, Codex, orchestrator, pairing relay, databases, and supporting services must not be recreated.
- The Mac must remain awake and online with Tailscale, Docker, Buzz, and the agents running for off-network phone access.

---

### Task 1: Route Live Mobile Pairing Through Tailscale

**Files:**
- Modify (ignored runtime): `/Users/s0m03qp/Desktop/AI-Labs/workpods-umbrella/.runtime/local-buzz-hermes/buzz-community-proxy.conf`
- Modify (ignored runtime): `/Users/s0m03qp/Desktop/AI-Labs/workpods-umbrella/.runtime/local-buzz-hermes/compose.buzz.yml`
- Test: live NIP-11, HTTPS, WebSocket, Docker, and Tailscale assertions

**Interfaces:**
- Consumes: main relay at `relay:3000`, pairing relay at `pairing:5000`, loopback proxy at `127.0.0.1:3330`, Tailscale hostname `m-dy0xcqpqvv.tail6733e0.ts.net`.
- Produces: `/` main-relay WebSocket route, `/pair` pairing-relay WebSocket route, and NIP-11 `pairing_relay_url` equal to the secure Tailscale URL.

- [ ] **Step 1: Record the protected container identities and states**

Create a temporary evidence file outside both repositories:

```bash
evidence_dir="$(mktemp -d)"
docker inspect \
  learning-hermes \
  learning-pi-chat-acp-poller \
  learning-codex-chat-acp \
  learning-orchestrator-chat-acp \
  learning-buzz-pairing \
  --format '{{.Name}} {{.Id}} {{.State.Status}}' \
  > "$evidence_dir/protected-before.txt"
```

Expected: all five listed containers exist; the four conversational-agent containers and pairing relay report `running`.

- [ ] **Step 2: Run the RED metadata assertion**

```bash
expected_pairing_url='wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair'
actual_pairing_url="$(
  curl -fsS --max-time 10 \
    -H 'Accept: application/nostr+json' \
    https://m-dy0xcqpqvv.tail6733e0.ts.net/ \
  | jq -r '.pairing_relay_url'
)"
test "$actual_pairing_url" = "$expected_pairing_url"
```

Expected: FAIL because the current value is `ws://pairing:5000`, proving the phone would receive a Docker-only endpoint.

- [ ] **Step 3: Add the dedicated `/pair` WebSocket route**

Insert this location before the existing `location /` block in the ignored runtime Nginx configuration:

```nginx
location = /pair {
  proxy_pass http://pairing:5000;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600s;
  proxy_send_timeout 3600s;
}
```

Do not change the existing main-relay host rewrite.

- [ ] **Step 4: Advertise the secure pairing URL**

Change only the relay environment value in the ignored runtime Compose file:

```yaml
BUZZ_PAIRING_RELAY_URL: wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair
```

Do not display or modify the ignored runtime `.env` file.

- [ ] **Step 5: Validate configuration before restarting anything**

```bash
cd /Users/s0m03qp/Desktop/AI-Labs/workpods-umbrella/.runtime/local-buzz-hermes
docker compose --env-file .env -f compose.buzz.yml config -q
docker run --rm \
  --network workpods-learning \
  --add-host=host.docker.internal:host-gateway \
  -v "$PWD/buzz-community-proxy.conf:/etc/nginx/nginx.conf:ro" \
  nginx:1.27-alpine nginx -t
```

Expected: both commands exit 0 and Nginx reports that the syntax is successful.

- [ ] **Step 6: Recreate only the proxy and main relay**

```bash
docker compose --env-file .env -f compose.buzz.yml \
  up -d --no-deps --force-recreate relay
docker compose --env-file .env -f compose.buzz.yml \
  up -d --no-deps --force-recreate community-proxy
```

Expected: only `learning-buzz-community-proxy` and `learning-buzz-relay` receive new container IDs.

- [ ] **Step 7: Run GREEN network and metadata assertions**

```bash
curl -fsS --connect-timeout 5 --max-time 10 \
  https://m-dy0xcqpqvv.tail6733e0.ts.net/_readiness \
  | jq -e '.status == "ready"'

actual_pairing_url="$(
  curl -fsS --max-time 10 \
    -H 'Accept: application/nostr+json' \
    https://m-dy0xcqpqvv.tail6733e0.ts.net/ \
  | jq -r '.pairing_relay_url'
)"
test "$actual_pairing_url" = \
  'wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair'
```

Expected: readiness is `ready` and the metadata assertion exits 0.

Verify the main and pairing WebSocket handshakes independently:

```javascript
import WebSocket from "ws";

const urls = [
  "wss://m-dy0xcqpqvv.tail6733e0.ts.net/",
  "wss://m-dy0xcqpqvv.tail6733e0.ts.net/pair",
];

for (const url of urls) {
  await new Promise((resolve, reject) => {
    const socket = new WebSocket(url);
    const timer = setTimeout(() => reject(new Error(`timeout: ${url}`)), 10000);
    socket.once("open", () => {
      clearTimeout(timer);
      socket.close();
      resolve();
    });
    socket.once("error", reject);
  });
  console.log(`OPEN ${url}`);
}
```

Run the snippet from `ai-agent-orchestration-lab`, where `ws` is installed. Expected: both URLs print `OPEN`.

- [ ] **Step 8: Verify service preservation and reconnect health**

```bash
docker inspect \
  learning-hermes \
  learning-pi-chat-acp-poller \
  learning-codex-chat-acp \
  learning-orchestrator-chat-acp \
  learning-buzz-pairing \
  --format '{{.Name}} {{.Id}} {{.State.Status}}' \
  > "$evidence_dir/protected-after.txt"

diff -u "$evidence_dir/protected-before.txt" "$evidence_dir/protected-after.txt"
docker ps --format '{{.Names}} {{.Status}}' \
  | rg 'learning-(hermes|pi-chat-acp-poller|codex-chat-acp|orchestrator-chat-acp)'
```

Expected: `diff` is empty and all four agent containers remain `Up`. Check recent logs for successful relay reconnection without printing environment values.

- [ ] **Step 9: Confirm no umbrella commit is possible**

```bash
git -C /Users/s0m03qp/Desktop/AI-Labs/workpods-umbrella status --short
```

Expected: no tracked change from this task. Do not commit in the umbrella repository.

---

### Task 2: Publish a Sanitized, Portable Pairing Configuration

**Files:**
- Modify: `compose/compose.buzz.yml`
- Modify: `compose/buzz-community-proxy.conf`
- Modify: `examples/runtime/buzz.env.example`
- Modify: `README.md`
- Test: Compose validation, repository tests, secret scan

**Interfaces:**
- Consumes: `BUZZ_PAIRING_RELAY_URL` from ignored `runtime/buzz.env`.
- Produces: a reusable Compose example that publishes the community proxy only on `127.0.0.1:3330`, routes `/pair` internally, and advertises an operator-supplied secure pairing URL.

- [ ] **Step 1: Run RED static assertions**

```bash
rg -q 'BUZZ_PAIRING_RELAY_URL: \$\{BUZZ_PAIRING_RELAY_URL:' compose/compose.buzz.yml
rg -q '127\.0\.0\.1:3330:3300' compose/compose.buzz.yml
rg -q 'location = /pair' compose/buzz-community-proxy.conf
rg -q '^BUZZ_PAIRING_RELAY_URL=wss://' examples/runtime/buzz.env.example
```

Expected: at least one command fails because the portable configuration is not implemented yet.

- [ ] **Step 2: Parameterize and publish only the community proxy**

Change the relay environment entry to:

```yaml
BUZZ_PAIRING_RELAY_URL: ${BUZZ_PAIRING_RELAY_URL:-ws://pairing:5000}
```

Add this to the `community-proxy` service:

```yaml
ports:
  - "127.0.0.1:3330:3300"
```

- [ ] **Step 3: Add the portable `/pair` route**

Add this exact location before the main `location /` block. Keep the main relay host rewrite unchanged.

```nginx
location = /pair {
  proxy_pass http://pairing:5000;
  proxy_http_version 1.1;
  proxy_set_header Host $host;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_read_timeout 3600s;
  proxy_send_timeout 3600s;
}
```

- [ ] **Step 4: Add a safe environment example**

Append this documented placeholder without any real tailnet or identity data:

```dotenv
# For private mobile pairing through Tailscale Serve; replace both labels.
BUZZ_PAIRING_RELAY_URL=wss://your-machine.your-tailnet.ts.net/pair
```

- [ ] **Step 5: Document private remote access**

Add a README section containing these operator steps:

```text
1. Install Tailscale on the host and phone and join the same tailnet.
2. Set BUZZ_PAIRING_RELAY_URL to wss://<machine>.<tailnet>.ts.net/pair.
3. Start the Compose stack and run `tailscale serve --bg 3330`.
4. Use https://<machine>.<tailnet>.ts.net as the Buzz community URL.
5. Pair through Desktop Settings > Mobile and verify the SAS on both devices.
```

State explicitly that Funnel is unnecessary and that the host must remain online.

- [ ] **Step 6: Run GREEN assertions and the full repository suite**

```bash
rg -q 'BUZZ_PAIRING_RELAY_URL: \$\{BUZZ_PAIRING_RELAY_URL:' compose/compose.buzz.yml
rg -q '127\.0\.0\.1:3330:3300' compose/compose.buzz.yml
rg -q 'location = /pair' compose/buzz-community-proxy.conf
rg -q '^BUZZ_PAIRING_RELAY_URL=wss://' examples/runtime/buzz.env.example
npm test
git diff --check
```

Expected: all static assertions exit 0, all 65 existing tests pass, and `git diff --check` is silent.

- [ ] **Step 7: Scan the staged change for secrets**

```bash
git add \
  compose/compose.buzz.yml \
  compose/buzz-community-proxy.conf \
  examples/runtime/buzz.env.example \
  README.md
git diff --cached --name-only
git diff --cached \
  | rg -n 'gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{20,}|BEGIN .*PRIVATE KEY|"private_key"[[:space:]]*:[[:space:]]*"[0-9a-fA-F]{64}"' \
  && exit 1 || true
```

Expected: only the four intended portable files are staged and no credential pattern is found. Review any descriptive documentation match manually before proceeding.

- [ ] **Step 8: Commit and push the portable configuration**

```bash
git commit -m "feat: add private Buzz mobile access"
git push origin main
```

Expected: the portfolio repository is clean and `origin/main` contains the sanitized configuration.

---

### Task 3: Pair the Existing Identity and Test Off-Network Access

**Files:**
- No repository files
- User-controlled state: Buzz Desktop secure identity store and Buzz Mobile secure storage

**Interfaces:**
- Consumes: verified NIP-11 pairing URL and working `/pair` WebSocket route.
- Produces: the existing `learning-user` identity stored on the iPhone and a successful remote Buzz session.

- [ ] **Step 1: Generate a fresh pairing session**

Open Buzz Desktop and select **Settings > Mobile > Start pairing**. Do not copy or log the QR payload. If a previous QR exists, cancel it and generate a new one after Task 1 is green.

- [ ] **Step 2: Scan and verify the identity transfer**

In Buzz Mobile, select **Scan a QR code**, grant camera permission, and scan the desktop QR. Compare the six-digit SAS shown on both devices. Confirm only if every digit matches; otherwise cancel and regenerate.

- [ ] **Step 3: Confirm the existing identity and community**

Expected after transfer:

```text
Identity: learning-user
Community URL: https://m-dy0xcqpqvv.tail6733e0.ts.net
Channel: AI Engineering Lab
Agents: hermes-learning, pi-chat, codex-chat, orchestrator-chat
```

- [ ] **Step 4: Prove access from a different network**

Turn off Wi-Fi on the iPhone so it uses cellular data. Keep Tailscale connected, reopen Buzz Mobile, and load `AI Engineering Lab`.

Send:

```text
@orchestrator-chat ask Hermes, Pi, and Codex to each explain one role they play in this lab, then synthesize their answers.
```

Expected: one task, three delegated asks, three worker replies, and one synthesis appear on the phone while it is not on the Mac's local network.

- [ ] **Step 5: Record only non-sensitive completion evidence**

Record that pairing completed, cellular access worked, and the orchestration response arrived. Do not save the QR, SAS code, private identity material, or full runtime logs.
