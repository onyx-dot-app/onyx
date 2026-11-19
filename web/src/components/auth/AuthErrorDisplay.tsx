"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { toast } from "@opal/layouts";

export default function AuthErrorDisplay({
  searchParams,
}: {
  searchParams: any;
}) {
  const t = useTranslations("auth.errorDisplay");
  const error = searchParams?.error;

  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- raises a toast for the auth error query param
  useEffect(() => {
    if (error) {
      toast.error(
        error === "Anonymous"
          ? t("anonymousDisabled.toast")
          : t("generic.toast")
      );
    }
  }, [error, t]);

  return null;
}
