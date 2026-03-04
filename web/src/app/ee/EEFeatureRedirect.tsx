"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { toast } from "@/hooks/useToast";

export default function EEFeatureRedirect() {
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    toast.error(
      `${pathname} is only accessible with a paid license. Please upgrade to use this feature.`
    );
    router.replace("/chat");
  }, [pathname, router]);

  return null;
}
