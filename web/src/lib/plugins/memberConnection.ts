import * as yup from "yup";
import type { PluginReference } from "@/lib/plugins/types";

export type MemberPluginConnectionFailure =
  | "popup_blocked"
  | "cancelled"
  | "timed_out"
  | "credentials_required"
  | "unconfigured"
  | "not_connected"
  | "request_failed";

export class MemberPluginConnectionError extends Error {
  constructor(readonly reason: MemberPluginConnectionFailure) {
    super(reason);
    this.name = "MemberPluginConnectionError";
  }
}

export interface MemberPluginConnectOptions {
  signal?: AbortSignal;
}

const completionType = "onyx:member-plugin-oauth-complete";
const completionSchema = yup.object({
  type: yup.mixed<typeof completionType>().oneOf([completionType]).defined(),
  attempt: yup.string().defined(),
});

function openCompletionChannel(attempt: string): BroadcastChannel | null {
  if (typeof BroadcastChannel === "undefined") return null;
  try {
    return new BroadcastChannel(`${completionType}:${attempt}`);
  } catch {
    return null;
  }
}

export function notifyMemberPluginOAuthComplete(attempt: string): void {
  const message = { type: completionType, attempt };
  try {
    window.opener?.postMessage(message, window.location.origin);
  } catch {}
  const channel = openCompletionChannel(attempt);
  if (!channel) return;
  try {
    channel.postMessage(message);
  } catch {
  } finally {
    channel.close();
  }
}

export function runMemberPluginOAuth(
  reference: PluginReference,
  start: (returnPath: string) => Promise<string | null>,
  { signal }: MemberPluginConnectOptions = {}
): Promise<void> {
  if (signal?.aborted) {
    return Promise.reject(new MemberPluginConnectionError("cancelled"));
  }
  const popup = window.open("about:blank", "_blank");
  if (!popup) {
    return Promise.reject(new MemberPluginConnectionError("popup_blocked"));
  }
  const attempt = crypto.randomUUID();
  const query = new URLSearchParams({
    pluginKind: reference.kind,
    pluginId: String(reference.id),
    attempt,
  });
  const returnPath = `/app/plugins/oauth/complete?${query.toString()}`;

  return new Promise((resolve, reject) => {
    let settled = false;
    const channel = openCompletionChannel(attempt);
    function finish(error?: MemberPluginConnectionError) {
      if (settled) return;
      settled = true;
      window.removeEventListener("message", receiveCompletion);
      signal?.removeEventListener("abort", cancel);
      channel?.removeEventListener("message", receiveBroadcastCompletion);
      channel?.close();
      window.clearTimeout(timeout);
      popup?.close();
      if (error) reject(error);
      else resolve();
    }
    function cancel() {
      finish(new MemberPluginConnectionError("cancelled"));
    }
    function receiveBroadcastCompletion(event: MessageEvent<unknown>) {
      try {
        const message = completionSchema.validateSync(event.data, {
          strict: true,
        });
        if (message.attempt === attempt) finish();
      } catch {}
    }
    function receiveCompletion(event: MessageEvent<unknown>) {
      if (event.origin !== window.location.origin || event.source !== popup)
        return;
      receiveBroadcastCompletion(event);
    }
    // COOP can mark a live popup closed. Wait for completion, explicit cancellation, or timeout.
    const timeout = window.setTimeout(
      () => {
        finish(new MemberPluginConnectionError("timed_out"));
      },
      5 * 60 * 1000
    );
    window.addEventListener("message", receiveCompletion);
    channel?.addEventListener("message", receiveBroadcastCompletion);
    signal?.addEventListener("abort", cancel, { once: true });
    start(returnPath).then(
      (authorizationUrl) => {
        if (settled) return;
        if (authorizationUrl === null) {
          finish();
          return;
        }
        try {
          const url = new URL(authorizationUrl);
          if (url.protocol !== "https:" && url.protocol !== "http:") {
            finish(new MemberPluginConnectionError("request_failed"));
            return;
          }
          popup.location.href = url.href;
        } catch {
          finish(new MemberPluginConnectionError("request_failed"));
        }
      },
      () => finish(new MemberPluginConnectionError("request_failed"))
    );
  });
}
