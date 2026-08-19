/**
 * Analytics utilities — type-safe PostHog event tracking.
 *
 * All PostHog `capture()` calls should go through `track()` rather than
 * calling `posthog.capture()` directly. This enforces that:
 *   - every event name is registered in `AnalyticsEvent` (greppable, no magic
 *     strings scattered across the codebase)
 *   - every event that carries data has its property shape declared in
 *     `AnalyticsEventProperties` (TypeScript catches missing or misspelled keys
 *     at the call site)
 *
 * To add a new event:
 *   1. Add a value to `AnalyticsEvent`.
 *   2. Add its property type to `AnalyticsEventProperties` (use `void` if the
 *      event carries no extra data).
 *   3. Call `track(AnalyticsEvent.YOUR_EVENT, { ... })` at the call site.
 */

import posthog from "posthog-js";

// ─── Event Registry ────────────────────────────────────────────────────────

/**
 * All tracked PostHog event names.
 *
 * Use these constants instead of inline strings so event usage is greppable
 * and typos are caught at compile time.
 */
export enum AnalyticsEvent {
  CONFIGURED_LLM_PROVIDER = "configured_llm_provider",
  COMPLETED_CRAFT_ONBOARDING = "completed_craft_onboarding",
  SENT_CRAFT_MESSAGE = "sent_craft_message",
  SAW_CRAFT_INTRO = "saw_craft_intro",
  CLICKED_GO_HOME = "clicked_go_home",
  CLICKED_TRY_CRAFT = "clicked_try_craft",
  CLICKED_CRAFT_IN_SIDEBAR = "clicked_craft_in_sidebar",
  RELEASE_NOTIFICATION_CLICKED = "release_notification_clicked",
  EXTENSION_CHAT_QUERY = "extension_chat_query",
}

// ─── Shared Enums ──────────────────────────────────────────────────────────

/**
 * Identifies which surface triggered an LLM provider configuration.
 * Sent as a property of `AnalyticsEvent.CONFIGURED_LLM_PROVIDER`.
 */
export enum LLMProviderConfiguredSource {
  ADMIN_PAGE = "admin_page",
  CHAT_ONBOARDING = "chat_onboarding",
  CRAFT_ONBOARDING = "craft_onboarding",
}

// ─── Event Property Types ──────────────────────────────────────────────────

/**
 * Maps each `AnalyticsEvent` to its required property shape.
 *
 * Use `void` for events that carry no extra data — this makes the second
 * argument to `track()` optional for those events while requiring it for
 * events that carry data.
 */
interface AnalyticsEventProperties {
  [AnalyticsEvent.CONFIGURED_LLM_PROVIDER]: {
    /** The provider identifier (e.g. "openai", "anthropic"). */
    provider: string;
    /** `true` if this is a new provider being added; `false` for an edit. */
    is_creation: boolean;
    /** Which surface the user configured the provider from. */
    source: LLMProviderConfiguredSource;
  };
  [AnalyticsEvent.COMPLETED_CRAFT_ONBOARDING]: void;
  [AnalyticsEvent.SENT_CRAFT_MESSAGE]: void;
  [AnalyticsEvent.SAW_CRAFT_INTRO]: void;
  [AnalyticsEvent.CLICKED_GO_HOME]: void;
  [AnalyticsEvent.CLICKED_TRY_CRAFT]: void;
  [AnalyticsEvent.CLICKED_CRAFT_IN_SIDEBAR]: void;
  [AnalyticsEvent.RELEASE_NOTIFICATION_CLICKED]: {
    /** Semver string of the release that was clicked, if available. */
    version: string | undefined;
  };
  [AnalyticsEvent.EXTENSION_CHAT_QUERY]: {
    /** The context string injected by the browser extension, if any. */
    extension_context: string | null | undefined;
    /** The ID of the assistant used for the query, if any. */
    assistant_id: number | undefined;
    /** Whether any files were attached to the query. */
    has_files: boolean;
    /** Whether deep research mode was active. */
    deep_research: boolean;
  };
}

// ─── Typed Track Function ──────────────────────────────────────────────────

/**
 * Fire a PostHog analytics event.
 *
 * The generic parameter `E` is inferred from the first argument, so
 * TypeScript will enforce the correct property shape for the second argument
 * and flag any missing or unexpected keys at the call site.
 *
 * @example
 * // Event with no properties:
 * track(AnalyticsEvent.SENT_CRAFT_MESSAGE);
 *
 * // Event with required properties:
 * track(AnalyticsEvent.CONFIGURED_LLM_PROVIDER, {
 *   provider: "openai",
 *   is_creation: true,
 *   source: LLMProviderConfiguredSource.ADMIN_PAGE,
 * });
 */
export function track<E extends AnalyticsEvent>(
  ...args: AnalyticsEventProperties[E] extends void
    ? [event: E]
    : [event: E, properties: AnalyticsEventProperties[E]]
): void {
  const [event, properties] = args as [E, Record<string, unknown>?];
  posthog.capture(event, properties ?? {});
}
