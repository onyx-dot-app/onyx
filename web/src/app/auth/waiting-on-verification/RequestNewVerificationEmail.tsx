"use client";

import { toast } from "@opal/layouts";
import { requestEmailVerification } from "../lib";
import { Spinner } from "@/components/Spinner";
import { ReactNode, useState } from "react";
import { useTranslations } from "next-intl";

export function RequestNewVerificationEmail({
  children,
  email,
}: {
  children: ReactNode;
  email: string;
}) {
  const t = useTranslations("auth");
  const [isRequestingVerification, setIsRequestingVerification] =
    useState(false);

  return (
    <button
      className="text-link"
      onClick={async () => {
        setIsRequestingVerification(true);
        const response = await requestEmailVerification(email);
        setIsRequestingVerification(false);

        if (response.ok) {
          toast.success(t("waitingOnVerification.emailSent.toast"));
        } else {
          const errorDetail = (await response.json()).detail;
          toast.error(
            t("waitingOnVerification.sendFailed.toast", { errorDetail })
          );
        }
      }}
    >
      {isRequestingVerification && <Spinner />}
      {children}
    </button>
  );
}
