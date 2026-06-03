"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// Admin app management moved to the admin panel. Keep this route as a redirect
// so existing links don't break.
export default function ExternalAppsAdminRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/admin/external-apps");
  }, [router]);
  return null;
}
