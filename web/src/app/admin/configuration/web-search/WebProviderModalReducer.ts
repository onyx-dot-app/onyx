export type WebProviderModalState = {
  /** Provider type currently being configured in the modal (null when closed). */
  providerType: string | null;

  /** Existing provider ID when editing (null for new providers). */
  existingProviderId: number | null;

  /** Raw API key input value (may be the masked placeholder). */
  apiKeyValue: string;
  /** Single provider-specific config field value (e.g. cx / base URL). */
  configValue: string;

  /** Request phase for disabling inputs/buttons. */
  phase: "idle" | "validating" | "saving";

  /**
   * UI message shown in the modal helper region.
   * - kind=error: red error message
   * - kind=status: neutral/green status message
   */
  message: { kind: "status" | "error"; text: string } | null;
};

export type WebProviderModalAction =
  | {
      type: "OPEN";
      providerType: string;
      existingProviderId: number | null;
      initialApiKeyValue: string;
      initialConfigValue: string;
    }
  | { type: "CLOSE" }
  | { type: "SET_API_KEY"; value: string }
  | { type: "SET_CONFIG_VALUE"; value: string }
  | { type: "SET_PHASE"; phase: "idle" | "validating" | "saving" }
  | { type: "SET_STATUS_MESSAGE"; text: string }
  | { type: "SET_ERROR_MESSAGE"; text: string }
  | { type: "CLEAR_MESSAGE" };

export const initialWebProviderModalState: WebProviderModalState = {
  providerType: null,
  existingProviderId: null,
  apiKeyValue: "",
  configValue: "",
  phase: "idle",
  message: null,
};

export const MASKED_API_KEY_PLACEHOLDER = "••••••••••••••••";

export function WebProviderModalReducer(
  state: WebProviderModalState,
  action: WebProviderModalAction
): WebProviderModalState {
  switch (action.type) {
    case "OPEN":
      return {
        ...state,
        providerType: action.providerType,
        existingProviderId: action.existingProviderId,
        apiKeyValue: action.initialApiKeyValue,
        configValue: action.initialConfigValue,
        phase: "idle",
        message: null,
      };
    case "CLOSE":
      return {
        ...state,
        providerType: null,
        existingProviderId: null,
        apiKeyValue: "",
        configValue: "",
        phase: "idle",
        message: null,
      };
    case "SET_API_KEY": {
      return {
        ...state,
        apiKeyValue: action.value,
      };
    }
    case "SET_CONFIG_VALUE":
      return {
        ...state,
        configValue: action.value,
      };
    case "SET_PHASE":
      return {
        ...state,
        phase: action.phase,
      };
    case "SET_STATUS_MESSAGE":
      return {
        ...state,
        message: { kind: "status", text: action.text },
      };
    case "SET_ERROR_MESSAGE":
      return {
        ...state,
        phase: "idle",
        message: { kind: "error", text: action.text },
      };
    case "CLEAR_MESSAGE":
      return {
        ...state,
        message: null,
      };
    default:
      return state;
  }
}
