"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/providers/UserProvider";
import SkillsPage from "@/refresh-pages/admin/SkillsPage";

// Org-wide skill management, surfaced inside the Craft UI (reached via "Manage
// skills" on the Skills page) rather than the global admin panel. Admins and
// curators only; everyone else bounces back to the skills they can use.
export default function ManageSkillsPage() {
  const router = useRouter();
  const { user, isAdmin, isCurator } = useUser();
  const allowed = isAdmin || isCurator;

  useEffect(() => {
    if (user && !allowed) router.replace("/craft/v1/skills");
  }, [user, allowed, router]);

  if (!allowed) return null;

  return <SkillsPage onBack={() => router.push("/craft/v1/skills")} />;
}
