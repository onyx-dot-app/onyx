"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { toast } from "@/hooks/useToast";

export default function EEFeatureRedirect() {
  const router = useRouter();

  useEffect(() => {
    toast.error(
      "This feature requires a license. Please upgrade your plan to access."
    );
    router.replace("/app");
  }, [router]);

  return null;
}
