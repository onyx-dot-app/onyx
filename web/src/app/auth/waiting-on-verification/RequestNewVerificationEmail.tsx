"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { requestEmailVerification } from "../lib";
import { Spinner } from "@/components/Spinner";
import { useState, JSX } from "react";

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
            message: "A new verification email has been sent!",
          });
        } else {
          const errorDetail = (await response.json()).detail;
          setPopup({
            type: "error",
            message: `Failed to send a new verification email - ${errorDetail}`,
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
