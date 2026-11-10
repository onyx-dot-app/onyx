import type { PluginReference } from "@/lib/plugins/types";
import {
  launchOAuth,
  OAuthLaunchError,
  oauthFailureDetail,
  type OAuthFailureDetail,
  type OAuthLaunchFailure,
} from "@/lib/oauth/launch";

export type MemberPluginConnectionFailure =
  | "popup_blocked"
  | "cancelled"
  | "timed_out"
  | "credentials_required"
  | "unconfigured"
  | "not_connected"
  | "request_failed";

export class MemberPluginConnectionError extends Error {
  constructor(
    readonly reason: MemberPluginConnectionFailure,
    readonly detail?: OAuthFailureDetail
  ) {
    super(reason);
    this.name = "MemberPluginConnectionError";
  }
}

export interface MemberPluginConnectOptions {
  signal?: AbortSignal;
  agentId?: number;
  surface?: "all" | "chat" | "craft";
}

const launchFailures: Record<
  OAuthLaunchFailure,
  MemberPluginConnectionFailure
> = {
  popup_blocked: "popup_blocked",
  cancelled: "cancelled",
  timed_out: "timed_out",
  failed: "not_connected",
  request_failed: "request_failed",
};

/**
 * Runs a member plugin's OAuth through `launchOAuth`: a new tab on the web,
 * the system browser in the desktop app. `start` receives the page the
 * callback redirects to when no waiting page closes it.
 */
export async function runMemberPluginOAuth(
  reference: PluginReference,
  start: (returnPath: string) => Promise<string | null>,
  { signal, agentId, surface }: MemberPluginConnectOptions = {}
): Promise<void> {
  if (signal?.aborted) throw new MemberPluginConnectionError("cancelled");
  const query = new URLSearchParams({
    pluginKind: reference.kind,
    pluginId: String(reference.id),
  });
  if (agentId !== undefined) query.set("agentId", String(agentId));
  if (surface !== undefined) query.set("surface", surface);
  const returnPath = `/app/plugins/oauth/complete?${query.toString()}`;
  try {
    await launchOAuth(() => start(returnPath), { signal });
  } catch (error) {
    if (error instanceof MemberPluginConnectionError) throw error;
    throw new MemberPluginConnectionError(
      error instanceof OAuthLaunchError
        ? launchFailures[error.reason]
        : "request_failed",
      oauthFailureDetail(error) ?? undefined
    );
  }
}
