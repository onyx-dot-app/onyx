"use client";

import { useNavigation } from "@opal/navigation";
import { useEffect } from "react";
import { useUser } from "@/providers/UserProvider";
import { useIsMultiTenant } from "@/lib/auth/hooks";
import { AccountsAccessSettings } from "@/views/SettingsPage";

export default function AccountsAccessPage() {
  const navigation = useNavigation();
  const { user } = useUser();
  const isMultiTenant = useIsMultiTenant();

  const showPasswordSection = Boolean(user?.password_configured);
  const showTokensSection = isMultiTenant !== null;
  const hasAccess = showPasswordSection || showTokensSection;

  // Only redirect after metadata has loaded to avoid redirecting during loading state
  const isAuthTypeLoaded = isMultiTenant !== null;

  useEffect(() => {
    if (isAuthTypeLoaded && !hasAccess) {
      navigation.go("/app/settings/general", { replace: true });
    }
  }, [isAuthTypeLoaded, hasAccess, navigation]);

  // Don't render content until metadata has loaded and access is determined
  if (!isAuthTypeLoaded || !hasAccess) {
    return null;
  }

  return <AccountsAccessSettings />;
}
