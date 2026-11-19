import type { MemberIntegration } from "@/lib/integrations/types";
import type { PluginNeed, PluginNeedState } from "@/lib/plugins/types";

/** Why a need has no action, shown as a muted note. */
export type PluginNeedNote =
  | "askAdmin"
  | "turnedOff"
  | "moreThanOne"
  | "notSupported";

/** The one thing a user can do for a need. */
export type PluginNeedAction =
  | { kind: "none" }
  | { kind: "turnOn"; integration: MemberIntegration }
  | { kind: "signIn"; integration: MemberIntegration }
  | { kind: "add" }
  | { kind: "note"; note: PluginNeedNote };

/** The need's state, read from the integration list when the need matches
 * one integration there. The first five need states are that integration's
 * own state, so the row follows a sign-in or a switch at once. */
export function liveNeedState(
  need: PluginNeed,
  integration: MemberIntegration | undefined
): PluginNeedState {
  return integration ? integration.access.state : need.state;
}

export function needAction(
  state: PluginNeedState,
  integration: MemberIntegration | undefined,
  canAddIntegrations: boolean
): PluginNeedAction {
  switch (state) {
    case "on":
      return { kind: "none" };
    case "turn_on":
      return integration ? { kind: "turnOn", integration } : { kind: "none" };
    case "sign_in":
      return integration ? { kind: "signIn", integration } : { kind: "none" };
    case "no_access":
      return { kind: "note", note: "askAdmin" };
    case "turned_off":
      return { kind: "note", note: "turnedOff" };
    case "not_added":
      return canAddIntegrations
        ? { kind: "add" }
        : { kind: "note", note: "askAdmin" };
    case "more_than_one":
      return { kind: "note", note: "moreThanOne" };
    case "not_supported":
      return { kind: "note", note: "notSupported" };
    default: {
      const unhandled: never = state;
      return unhandled;
    }
  }
}

/** A supported need that is not on: the turn-on dialog lists the needs. */
export function needsAttention(needs: readonly PluginNeed[]): boolean {
  return needs.some((need) => need.supported && need.state !== "on");
}

/** The transport of the Add integration form for an MCP need. */
export function needTransport(need: PluginNeed): "STREAMABLE_HTTP" | "SSE" {
  return need.transport === "sse" ? "SSE" : "STREAMABLE_HTTP";
}
