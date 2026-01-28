"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/components/user/UserProvider";
import { useAuthType } from "@/lib/hooks";
import { AuthType } from "@/lib/constants";
import { AccountsAccessSettings } from "@/refresh-pages/SettingsPage";

export default function AccountsAccessPage() {
  const router = useRouter();
  const { user } = useUser();
  const authType = useAuthType();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = authType !== null && authType !== AuthType.DISABLED;
  const hasAccess = showPasswordSection || showTokensSection;

  // Only redirect after authType has loaded to avoid redirecting during loading state
  const isAuthTypeLoaded = authType !== null;

  useEffect(() => {
    if (isAuthTypeLoaded && !hasAccess) {
      router.replace("/app/settings/general");
    }
  }, [isAuthTypeLoaded, hasAccess, router]);

  // Don't render content until authType is loaded and access is determined
  if (!isAuthTypeLoaded || !hasAccess) {
    return null;
  }

  return <AccountsAccessSettings />;
}
