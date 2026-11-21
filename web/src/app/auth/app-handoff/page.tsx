"use client";

import { useEffect, useState } from "react";
import { loadPage, useNavigation } from "@opal/navigation";
import { isAppSignInHandoff } from "@/lib/auth/appHandoff";
import { ReturnToAppCard } from "@/sections/oauth/DesktopOAuthHandoff";

// The sign-in callback sends a desktop browser here with the app's deep link
// in the fragment. The page opens the app, so the tab ends on an Onyx page.
export default function AppSignInHandoffPage() {
  const navigation = useNavigation();
  const [deepLink, setDeepLink] = useState<string | null>(null);

  useEffect(() => {
    let link: string | null = null;
    try {
      link = decodeURIComponent(window.location.hash.slice(1));
    } catch {
      link = null;
    }
    // The link carries a one-time code; keep it out of the tab's history.
    navigation.go("/auth/app-handoff", { replace: true, shallow: true });
    if (!isAppSignInHandoff(link)) return;
    setDeepLink(link);
    loadPage(link);
  }, [navigation]);

  return <ReturnToAppCard returnUrl={deepLink} />;
}
