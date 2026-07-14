"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/providers/UserProvider";
import { AccountsAccessSettings } from "@/views/SettingsPage";

export default function AccountsAccessPage() {
  const router = useRouter();
  const { user } = useUser();

  const showPasswordSection = Boolean(user?.password_configured);
  const hasAccess = showPasswordSection || /* tokens always available */ true;

  useEffect(() => {
    if (!hasAccess) {
      router.replace("/app/settings/general");
    }
  }, [hasAccess, router]);

  if (!hasAccess) {
    return null;
  }

  return <AccountsAccessSettings />;
}
