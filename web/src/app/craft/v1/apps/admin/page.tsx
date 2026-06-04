"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// /craft/v1/apps/admin was the shipped admin apps page before management moved
// to /craft/v1/apps/manage; redirect so bookmarks to the old path still work.
export default function ExternalAppsAdminRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/craft/v1/apps/manage");
  }, [router]);
  return null;
}
