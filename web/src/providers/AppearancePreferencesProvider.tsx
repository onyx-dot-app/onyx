"use client";

import { useEffect } from "react";
import { useUser } from "@/providers/UserProvider";
import { applyAppearance } from "@/lib/appearance/preferences";

/**
 * Applies the user's saved appearance preferences to the document. The server
 * layout renders them on first paint from the appearance cookie; this keeps
 * <html> in step after a save or a newer /me.
 */
interface AppearancePreferencesProviderProps {
  children: React.ReactNode;
}

export function AppearancePreferencesProvider({
  children,
}: AppearancePreferencesProviderProps) {
  const { user } = useUser();
  const interfaceFont = user?.preferences.interface_font;
  const responseFont = user?.preferences.response_font;

  useEffect(() => {
    if (!interfaceFont || !responseFont) return;
    applyAppearance({
      interface_font: interfaceFont,
      response_font: responseFont,
    });
  }, [interfaceFont, responseFont]);

  return <>{children}</>;
}
