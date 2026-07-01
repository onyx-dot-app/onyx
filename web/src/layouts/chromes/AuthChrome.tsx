"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { useAuthDocumentTitle } from "@/lib/app/hooks";

interface AuthChromeProps {
  children: React.ReactNode;
}

export default function AuthChrome({ children }: AuthChromeProps) {
  const { appName } = useSettings();
  useAuthDocumentTitle(appName);
  return <AuthLayouts.Root>{children}</AuthLayouts.Root>;
}
