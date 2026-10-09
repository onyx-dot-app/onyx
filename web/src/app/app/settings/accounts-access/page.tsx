"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/providers/UserProvider";
import { useIsMultiTenant } from "@/lib/auth/hooks";
import { AccountsAccessSettings } from "@/views/SettingsPage";

export default function AccountsAccessPage() {
  const router = useRouter();
  const { user } = useUser();
  const isMultiTenant = useIsMultiTenant();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = isMultiTenant !== null;
  const hasAccess = showPasswordSection || showTokensSection;

  // Only redirect after metadata has loaded to avoid redirecting during loading state
  const isAuthTypeLoaded = isMultiTenant !== null;

  useEffect(() => {
    if (isAuthTypeLoaded && !hasAccess) {
      router.replace("/app/settings/general");
    }
  }, [isAuthTypeLoaded, hasAccess, router]);

  // Don't render content until metadata has loaded and access is determined
  if (!isAuthTypeLoaded || !hasAccess) {
    return null;
  }

  return <AccountsAccessSettings />;
}
