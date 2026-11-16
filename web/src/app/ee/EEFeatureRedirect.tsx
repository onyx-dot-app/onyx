"use client";

import { useNavigation } from "@opal/navigation";
import { useEffect } from "react";
import { toast } from "@opal/layouts";

export default function EEFeatureRedirect() {
  const navigation = useNavigation();

  useEffect(() => {
    toast.error(
      "This feature requires a license. Please upgrade your plan to access."
    );
    navigation.go("/app", { replace: true });
  }, [navigation]);

  return null;
}
