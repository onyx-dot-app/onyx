"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { usePopup } from "@/components/admin/connectors/Popup";

export default function EEFeatureRedirect() {
  const router = useRouter();
  const { setPopup } = usePopup();

  useEffect(() => {
    setPopup({
      message:
        "This feature requires a license. Please upgrade your plan to access.",
      type: "error",
    });
    router.replace("/app");
  }, [router, setPopup]);

  return null;
}
