import { readFile } from "node:fs/promises";
import { pathToFileURL } from "node:url";

import WebSocket from "ws";
import { finalizeEvent, Relay } from "nostr-tools";

export function buildProfile(channelId, humanPubkey) {
  return {
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
  };
}

export function finalizeAuthEvent(template, secretKey) {
  return finalizeEvent(template, secretKey);
}

export async function publishAfterAuthentication(
  relay,
  event,
  authenticationRequested,
) {
  await authenticationRequested;
  if (!relay.authPromise) {
    throw new Error("relay did not start NIP-42 authentication");
  }
  await relay.authPromise;
  await relay.publish(event);
}

function requiredEnvironment(name) {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is required`);
  }
  return value;
}

async function main() {
  const identityPath = requiredEnvironment("ORCHESTRATOR_IDENTITY_FILE");
  const relayUrl = requiredEnvironment("BUZZ_RELAY_URL");
  const channelId = requiredEnvironment("AI_ENGINEERING_LAB_CHANNEL_ID");
  const humanPubkey = requiredEnvironment("HUMAN_PUBKEY");
  const identity = JSON.parse(await readFile(identityPath, "utf8"));

  if (!/^[0-9a-f]{64}$/.test(identity.private_key ?? "")) {
    throw new Error("orchestrator identity has no valid private key");
  }

  const secretKey = Uint8Array.from(Buffer.from(identity.private_key, "hex"));
  const event = finalizeEvent(
    {
      kind: 10100,
      created_at: Math.floor(Date.now() / 1000),
      tags: [],
      content: JSON.stringify(buildProfile(channelId, humanPubkey)),
    },
    secretKey,
  );

  const relay = new Relay(relayUrl, { websocketImplementation: WebSocket });
  let markAuthenticationRequested;
  const authenticationRequested = new Promise((resolve) => {
    markAuthenticationRequested = resolve;
  });
  relay.onauth = async (template) => {
    markAuthenticationRequested();
    return finalizeAuthEvent(template, secretKey);
  };

  try {
    await relay.connect();
    await publishAfterAuthentication(relay, event, authenticationRequested);
    console.log(JSON.stringify({ event_id: event.id, pubkey: event.pubkey }));
  } finally {
    relay.close();
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  await main();
}
