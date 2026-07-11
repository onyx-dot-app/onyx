"use client";

import { useRouter } from "next/navigation";
import ExternalAppsPage from "@/views/admin/ExternalAppsPage";

// Admin-only org app configuration (gated server-side by CraftManageLayout).
export default function ManageAppsPage() {
  const router = useRouter();
  return <ExternalAppsPage onBack={() => router.push("/craft/v1/apps")} />;
}
