import posthog from "posthog-js";

// ─── Event Registry ────────────────────────────────────────────────────────
// All tracked event names. Add new events here to get type-safe tracking.

export enum AnalyticsEvent {
  CONFIGURED_LLM_PROVIDER = "configured_llm_provider",
  COMPLETED_CRAFT_ONBOARDING = "completed_craft_onboarding",
  COMPLETED_CRAFT_USER_INFO = "completed_craft_user_info",
  SENT_CRAFT_MESSAGE = "sent_craft_message",
  SAW_CRAFT_INTRO = "saw_craft_intro",
  RELEASE_NOTIFICATION_CLICKED = "release_notification_clicked",
  EXTENSION_CHAT_QUERY = "extension_chat_query",
}

// ─── Autocapture Actions ───────────────────────────────────────────────────
// Simple click events handled by PostHog autocapture. Use `autoCapture()`
// to get the data attribute for a given action. PostHog picks these up
// automatically from the `data-ph-capture-attribute-action` attribute on
// the clicked element, so no manual `track()` call is needed.

export enum AutoCaptureAction {
  CLICKED_GO_HOME = "clicked_go_home",
  CLICKED_TRY_CRAFT = "clicked_try_craft",
  CLICKED_CRAFT_IN_SIDEBAR = "clicked_craft_in_sidebar",
}

/**
 * Returns a props object with the PostHog autocapture data attribute.
 * Spread onto any clickable element to tag it for autocapture.
 *
 * @example
 * <button {...autoCapture(AutoCaptureAction.CLICKED_GO_HOME)} onClick={onClose}>
 *   Return Home
 * </button>
 */
export function autoCapture(action: AutoCaptureAction) {
  return { "data-ph-capture-attribute-action": action } as const;
}

// ─── Shared Enums ──────────────────────────────────────────────────────────

export enum LLMProviderConfiguredSource {
  ADMIN_PAGE = "admin_page",
  CHAT_ONBOARDING = "chat_onboarding",
  CRAFT_ONBOARDING = "craft_onboarding",
}

// ─── Event Property Types ──────────────────────────────────────────────────
// Maps each event to its required properties. Use `void` for events with no
// properties — this makes the second argument to `track()` optional for those
// events while requiring it for events that carry data.

interface AnalyticsEventProperties {
  [AnalyticsEvent.CONFIGURED_LLM_PROVIDER]: {
    provider: string;
    is_creation: boolean;
    source: LLMProviderConfiguredSource;
  };
  [AnalyticsEvent.COMPLETED_CRAFT_ONBOARDING]: void;
  [AnalyticsEvent.COMPLETED_CRAFT_USER_INFO]: {
    first_name: string;
    last_name: string | undefined;
    work_area: string | undefined;
    level: string | undefined;
  };
  [AnalyticsEvent.SENT_CRAFT_MESSAGE]: void;
  [AnalyticsEvent.SAW_CRAFT_INTRO]: void;
  [AnalyticsEvent.RELEASE_NOTIFICATION_CLICKED]: {
    version: string | undefined;
  };
  [AnalyticsEvent.EXTENSION_CHAT_QUERY]: {
    extension_context: string | null | undefined;
    assistant_id: number | undefined;
    has_files: boolean;
    deep_research: boolean;
  };
}

// ─── Typed Track Function ──────────────────────────────────────────────────

export function track<E extends AnalyticsEvent>(
  ...args: AnalyticsEventProperties[E] extends void
    ? [event: E]
    : [event: E, properties: AnalyticsEventProperties[E]]
): void {
  const [event, properties] = args as [E, Record<string, unknown>?];
  posthog.capture(event, properties ?? {});
}
