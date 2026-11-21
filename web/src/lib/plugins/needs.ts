import type { MemberIntegration } from "@/lib/integrations/types";
import type { PluginNeed, PluginNeedState } from "@/lib/plugins/types";

export type PluginNeedNote =
  | "askAdmin"
  | "turnedOff"
  | "moreThanOne"
  | "notSupported";

export type PluginNeedAction =
  | { kind: "none" }
  | { kind: "turnOn"; integration: MemberIntegration }
  | { kind: "signIn"; integration: MemberIntegration }
  | { kind: "add" }
  | { kind: "note"; note: PluginNeedNote };

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

export function needsAttention(needs: readonly PluginNeed[]): boolean {
  return needs.some((need) => need.supported && need.state !== "on");
}

export function needTransport(need: PluginNeed): "STREAMABLE_HTTP" | "SSE" {
  return need.transport === "sse" ? "SSE" : "STREAMABLE_HTTP";
}
