import assert from "node:assert/strict";
import test from "node:test";

import {
  buildProfile,
  finalizeAuthEvent,
  publishAfterAuthentication,
} from "../publish_agent_profile.mjs";

test("buildProfile returns the exact public orchestrator directory profile", () => {
  const channelId = "0426f95d-3339-42df-9592-837b3b5506da";
  const humanPubkey = "0".repeat(64);

  assert.deepStrictEqual(buildProfile(channelId, humanPubkey), {
    name: "orchestrator-chat",
    display_name: "orchestrator-chat",
    agent_type: "orchestrator",
    channels: ["AI Engineering Lab"],
    channel_ids: [channelId],
    capabilities: ["coordination", "delegation", "synthesis"],
    status: "online",
    channel_add_policy: "owner_only",
    respond_to: "allowlist",
    respond_to_allowlist: [humanPubkey],
  });
});

test("finalizeAuthEvent signs the NIP-42 template supplied by Relay", () => {
  const secretKey = new Uint8Array(32);
  secretKey[31] = 1;
  const template = {
    kind: 22242,
    created_at: 1_787_616_000,
    tags: [
      ["relay", "ws://buzz.localtest.me:3300"],
      ["challenge", "public-challenge"],
    ],
    content: "",
  };

  const event = finalizeAuthEvent(template, secretKey);

  assert.equal(event.kind, 22242);
  assert.deepStrictEqual(event.tags, template.tags);
  assert.match(event.id, /^[0-9a-f]{64}$/);
  assert.match(event.pubkey, /^[0-9a-f]{64}$/);
});

test("publishAfterAuthentication waits for NIP-42 acceptance", async () => {
  const calls = [];
  let acceptAuthentication;
  const authenticationAccepted = new Promise((resolve) => {
    acceptAuthentication = () => {
      calls.push("authenticated");
      resolve();
    };
  });
  let requestAuthentication;
  const relay = {
    authPromise: undefined,
    async publish() {
      calls.push("published");
    },
  };
  const authenticationRequested = new Promise((resolve) => {
    requestAuthentication = () => {
      relay.authPromise = authenticationAccepted;
      calls.push("auth-requested");
      resolve();
    };
  });

  const publishing = publishAfterAuthentication(
    relay,
    { id: "public-event-id" },
    authenticationRequested,
  );
  requestAuthentication();
  await Promise.resolve();
  assert.deepStrictEqual(calls, ["auth-requested"]);

  acceptAuthentication();
  await publishing;
  assert.deepStrictEqual(calls, [
    "auth-requested",
    "authenticated",
    "published",
  ]);
});

test("import preserves an existing WebSocket global without runtime work", async () => {
  const originalWebSocket = globalThis.WebSocket;
  const originalIdentityFile = process.env.ORCHESTRATOR_IDENTITY_FILE;
  const originalConsoleLog = console.log;
  const stdout = [];
  let networkCalls = 0;
  class SentinelWebSocket {
    constructor() {
      networkCalls += 1;
    }
  }

  globalThis.WebSocket = SentinelWebSocket;
  process.env.ORCHESTRATOR_IDENTITY_FILE = "/path/that/must/not/be/read.json";
  console.log = (...args) => stdout.push(args);
  try {
    const publisherUrl = new URL(
      `../publish_agent_profile.mjs?import-safety=${Date.now()}`,
      import.meta.url,
    );
    await import(publisherUrl.href);

    assert.strictEqual(globalThis.WebSocket, SentinelWebSocket);
    assert.deepStrictEqual(stdout, []);
    assert.equal(networkCalls, 0);
  } finally {
    globalThis.WebSocket = originalWebSocket;
    console.log = originalConsoleLog;
    if (originalIdentityFile === undefined) {
      delete process.env.ORCHESTRATOR_IDENTITY_FILE;
    } else {
      process.env.ORCHESTRATOR_IDENTITY_FILE = originalIdentityFile;
    }
  }
});
