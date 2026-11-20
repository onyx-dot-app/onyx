"use client";

import { useCallback } from "react";
import { useTheme } from "next-themes";
import { useUser } from "@/providers/UserProvider";
import { ThemePreference } from "@/lib/types";
import {
  CHAT_BACKGROUND_NONE,
  type ChatBackgroundOption,
} from "@/lib/constants/chatBackgrounds";

/**
 * Saves the theme and the chat background. The theme applies at once; a
 * background with its own theme also switches to that theme once the
 * background is saved.
 */
export function useAppearancePreferences() {
  const { updatePreferences } = useUser();
  const { setTheme } = useTheme();

  const chooseTheme = useCallback(
    async (theme: ThemePreference): Promise<boolean> => {
      setTheme(theme);
      return updatePreferences(
        { theme_preference: theme },
        "/api/user/theme-preference"
      );
    },
    [setTheme, updatePreferences]
  );

  const chooseChatBackground = useCallback(
    async (background: ChatBackgroundOption): Promise<boolean> => {
      const saved = await updatePreferences(
        {
          chat_background:
            background.id === CHAT_BACKGROUND_NONE ? null : background.id,
        },
        "/api/user/chat-background"
      );
      if (!saved || !background.theme) return saved;
      return chooseTheme(background.theme);
    },
    [chooseTheme, updatePreferences]
  );

  return { chooseTheme, chooseChatBackground };
}
