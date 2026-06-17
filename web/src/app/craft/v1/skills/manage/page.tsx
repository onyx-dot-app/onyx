"use client";

import { useRouter } from "next/navigation";
import SkillsPage from "@/refresh-pages/admin/SkillsPage";

// Admin-only org skill management (gated server-side by CraftManageLayout).
export default function ManageSkillsPage() {
  const router = useRouter();
  return <SkillsPage onBack={() => router.push("/craft/v1/skills")} />;
}
