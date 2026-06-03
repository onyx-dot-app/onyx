"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// App management now lives at /craft/v1/apps/manage. Keep this route as a
// redirect so existing links don't break.
export default function ExternalAppsAdminRedirect() {
  const router = useRouter();
  useEffect(() => {
    router.replace("/craft/v1/apps/manage");
  }, [router]);
  return null;
}
