"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

import { usePopup } from "@/components/admin/connectors/Popup";
import { requestEmailVerification } from "../lib";
import { Spinner } from "@/components/Spinner";
import { JSX, useState } from "react";

export function RequestNewVerificationEmail({
  children,
  email,
}: {
  children: JSX.Element | string;
  email: string;
}) {
  const { popup, setPopup } = usePopup();
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
          setPopup({
            type: "success",
            message: i18n.t(k.A_NEW_VERIFICATION_EMAIL_HAS_B),
          });
        } else {
          const errorDetail = (await response.json()).detail;
          setPopup({
            type: "error",
            message: `${i18n.t(
              k.FAILED_TO_SEND_A_NEW_VERIFICAT
            )} ${errorDetail}`,
          });
        }
      }}
    >
      {isRequestingVerification && <Spinner />}
      {popup}
      {children}
    </button>
  );
}
