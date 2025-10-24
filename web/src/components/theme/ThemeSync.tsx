"use client";

import { useEffect, useRef } from "react";
import { useTheme } from "next-themes";
import { useUser } from "@/components/user/UserProvider";

/**
 * Syncs the user's saved theme preference from the database to next-themes.
 * This ensures theme consistency across devices and browsers.
 */
export function ThemeSync() {
  const { user } = useUser();
  const { setTheme, theme } = useTheme();
  const hasSyncedRef = useRef(false);

  useEffect(() => {
    // Only sync once per session
    if (hasSyncedRef.current) return;

    // Wait for next-themes to initialize
    if (!theme) return;

    // Wait for user data to load
    if (!user?.id) return;

    // Only sync if user has a saved preference
    const savedTheme = user?.preferences?.theme_preference;
    if (!savedTheme) return;

    // Sync DB theme to localStorage
    setTheme(savedTheme);
    hasSyncedRef.current = true;
  }, [user?.id, user?.preferences?.theme_preference, theme, setTheme]);

  return null;
}
