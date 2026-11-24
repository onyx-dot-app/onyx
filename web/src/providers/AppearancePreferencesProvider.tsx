"use client";

import { createContext, useEffect } from "react";
import { MotionConfig } from "motion/react";
import { toast } from "@opal/layouts";
import { useUser } from "@/providers/UserProvider";
import {
  applyAppearance,
  DEFAULT_APPEARANCE_SETTINGS,
} from "@/lib/appearance/preferences";

/**
 * Whether the chat unloads messages far off screen. False keeps every
 * message loaded and mounted, so screen readers can reach all of them. A
 * boolean of its own, so chat rows re-render only when this preference
 * changes.
 */
export const DynamicConversationsContext = createContext(
  DEFAULT_APPEARANCE_SETTINGS.dynamic_conversations
);

/**
 * The one client owner of the user's saved appearance preferences:
 * - Fonts and motion: the `<html>` attributes. The server layout renders them
 *   on first paint from the appearance cookie; this keeps them in step after
 *   a save or a newer /me. CSS, Opal's motion variants and
 *   `prefersReducedMotion()` read `data-motion`.
 * - Motion inside React: `MotionConfig` for motion/react.
 * - Notifications: the default duration of toasts.
 * - Dynamic conversations: `DynamicConversationsContext`, read by the chat.
 */
interface AppearancePreferencesProviderProps {
  children: React.ReactNode;
}

export function AppearancePreferencesProvider({
  children,
}: AppearancePreferencesProviderProps) {
  const preferences = useUser().user?.preferences;
  const interfaceFont = preferences?.interface_font;
  const responseFont = preferences?.response_font;
  const motion = preferences?.motion;
  const persistentToasts = preferences?.popup_dismissal === "stay_on_screen";
  const dynamicConversations =
    preferences?.dynamic_conversations ??
    DEFAULT_APPEARANCE_SETTINGS.dynamic_conversations;

  useEffect(() => {
    if (!interfaceFont || !responseFont || !motion) return;
    applyAppearance({
      interface_font: interfaceFont,
      response_font: responseFont,
      motion,
    });
  }, [interfaceFont, responseFont, motion]);

  useEffect(() => {
    toast.setPersistentByDefault(persistentToasts);
    return () => toast.setPersistentByDefault(false);
  }, [persistentToasts]);

  // Motion components read this when they mount, so before /me loads it
  // comes from the attribute the server rendered from the saved preference.
  const reducedMotion = preferences
    ? motion === "reduced"
    : typeof document !== "undefined" &&
      document.documentElement.dataset.motion === "reduced";

  return (
    <MotionConfig reducedMotion={reducedMotion ? "always" : "user"}>
      <DynamicConversationsContext.Provider value={dynamicConversations}>
        {children}
      </DynamicConversationsContext.Provider>
    </MotionConfig>
  );
}
