"use client";

import { useRouter } from "next/navigation";
import SkillsPage from "@/refresh-pages/admin/SkillsPage";

// Org-wide skill management, surfaced inside the Craft UI. Admin-only access is
// enforced server-side by the shared CraftManageLayout.
export default function ManageSkillsPage() {
  const router = useRouter();
  return <SkillsPage onBack={() => router.push("/craft/v1/skills")} />;
}
