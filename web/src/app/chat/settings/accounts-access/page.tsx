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
  const showTokensSection = authType && authType !== AuthType.DISABLED;
  const hasAccess = showPasswordSection || showTokensSection;

  useEffect(() => {
    if (!hasAccess) {
      router.replace("/chat/settings/general");
    }
  }, [hasAccess, router]);

  // Don't render content if user doesn't have access
  if (!hasAccess) {
    return null;
  }

  return <AccountsAccessSettings />;
}
