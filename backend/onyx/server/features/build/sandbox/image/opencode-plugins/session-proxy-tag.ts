// Splices the originating BuildSession id into HTTP(S)_PROXY userinfo so the
// egress proxy can route approval cards to the exact session.
//
// The id is captured once at init from opencode-serve's per-Instance
// `?directory=` (the session workspace), not the per-command cwd, so
// `cd /tmp && curl` still carries the right tag. For HTTPS it travels on the
// CONNECT as Proxy-Authorization (hop-by-hop) and never reaches the origin.
// No-op when no proxy is configured (HTTP(S)_PROXY unset).

import type { Plugin } from "@opencode-ai/plugin";

const SESSION_DIR_RE =
  /\/sessions\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\/|$)/;

function taggedProxyUrl(
  base: string | undefined,
  sessionId: string
): string | undefined {
  if (!base) return undefined;
  try {
    const url = new URL(base);
    // The proxy treats the username as the session tag and discards the password
    return `${url.protocol}//${encodeURIComponent(sessionId)}:x@${url.host}`;
  } catch {
    return undefined;
  }
}

export default (async ({ directory }) => {
  const sessionId = directory.match(SESSION_DIR_RE)?.[1];
  // Not a session workspace (e.g. the server's launch-cwd Instance): leave
  // the proxy env untouched and let the proxy fall back to its src-IP heuristic.
  if (!sessionId) return {};

  return {
    "shell.env": async (_input, output) => {
      const https = taggedProxyUrl(
        process.env.HTTPS_PROXY ?? process.env.https_proxy,
        sessionId
      );
      const http = taggedProxyUrl(
        process.env.HTTP_PROXY ?? process.env.http_proxy,
        sessionId
      );
      if (https) {
        output.env.HTTPS_PROXY = https;
        output.env.https_proxy = https;
      }
      if (http) {
        output.env.HTTP_PROXY = http;
        output.env.http_proxy = http;
      }
    },
  };
}) satisfies Plugin;
