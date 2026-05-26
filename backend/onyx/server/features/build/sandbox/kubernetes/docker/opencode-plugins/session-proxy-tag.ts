// Onyx Craft — per-session egress tagging plugin.
//
// Tags every shell/bash subprocess request with the originating
// BuildSession id, carried as the Proxy-Authorization username, so the
// sandbox egress proxy can route approval cards to the *exact* session
// instead of falling back to the most-recent-active heuristic.
//
// How it works
// ------------
// - opencode-serve resolves one Instance (and one plugin instance) per
//   `?directory=` value. The serve client sets that to the session
//   workspace `/workspace/sessions/<build_session_id>`, so `directory`
//   below is exactly that path and the UUID in it is the BuildSession id.
//   (The session id is captured once at init from `directory`, not from
//   the per-command cwd, so `cd /tmp && curl` inside a session still
//   carries the right tag.)
// - firewall-init already sets HTTP(S)_PROXY to the proxy. We only splice
//   the session id into that URL's userinfo; NO_PROXY and the CA-bundle
//   env vars are inherited from process.env unchanged.
// - For HTTPS the userinfo travels on the CONNECT as Proxy-Authorization
//   (hop-by-hop, consumed by the proxy) — it never reaches the origin, so
//   it does not collide with any real Authorization header.
//
// Registered pod-wide via OPENCODE_CONFIG_CONTENT (see
// kubernetes_sandbox_manager + opencode_config.build_multi_provider_opencode_config).
// No-op when no proxy is configured (dev/local) — HTTP(S)_PROXY is unset,
// so there is nothing to tag.

import type { Plugin } from "@opencode-ai/plugin";

// Matches the session workspace path `/.../sessions/<uuid>` (optionally
// with a trailing slash or subpath).
const SESSION_DIR_RE =
  /\/sessions\/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(?:\/|$)/;

function taggedProxyUrl(
  base: string | undefined,
  sessionId: string
): string | undefined {
  if (!base) return undefined;
  try {
    const url = new URL(base);
    // Keep scheme + host:port, inject the session id as the basic-auth
    // username, drop any path. Password is intentionally empty (the
    // per-pod shared-secret hardening is deferred; the proxy's src-IP
    // anchor already bounds tag tampering to within the same user).
    return `${url.protocol}//${encodeURIComponent(sessionId)}@${url.host}`;
  } catch {
    return undefined;
  }
}

export default (async ({ directory }) => {
  const sessionId = directory.match(SESSION_DIR_RE)?.[1];
  // Not a session workspace (e.g. the server's launch-cwd Instance, used
  // by opencode's own egress) — leave the proxy env untouched; the proxy
  // resolves those by the src-IP heuristic.
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
