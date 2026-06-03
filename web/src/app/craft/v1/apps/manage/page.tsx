"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/providers/UserProvider";
import ExternalAppsPage from "@/refresh-pages/admin/ExternalAppsPage";

// Org-wide external app configuration, surfaced inside the Craft UI (reached
// via "Manage apps" on the Apps page) rather than the global admin panel.
// Admins and curators only; everyone else bounces back to their connections.
export default function ManageAppsPage() {
  const router = useRouter();
  const { user, isAdmin, isCurator } = useUser();
  const allowed = isAdmin || isCurator;

  useEffect(() => {
    if (user && !allowed) router.replace("/craft/v1/apps");
  }, [user, allowed, router]);

  if (!allowed) return null;

  return <ExternalAppsPage onBack={() => router.push("/craft/v1/apps")} />;
}
