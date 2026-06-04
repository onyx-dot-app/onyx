"use client";

import { useRouter } from "next/navigation";
import ExternalAppsPage from "@/refresh-pages/admin/ExternalAppsPage";

// Org-wide external app configuration, surfaced inside the Craft UI. Admin-only
// access is enforced server-side by the shared CraftManageLayout.
export default function ManageAppsPage() {
  const router = useRouter();
  return <ExternalAppsPage onBack={() => router.push("/craft/v1/apps")} />;
}
