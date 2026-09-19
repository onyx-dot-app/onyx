"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Text } from "@opal/components";
import { Spacer } from "@opal/components";
import { RequestNewVerificationEmail } from "../waiting-on-verification/RequestNewVerificationEmail";
import { User } from "@/lib/types";
import { Logo } from "@/lib/app/components";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useTranslations } from "next-intl";

export interface VerifyProps {
  user: User | null;
}

export default function Verify({ user }: VerifyProps) {
  const t = useTranslations("auth");
  const searchParams = useSearchParams();

  const [error, setError] = useState("");

  const verify = useCallback(async () => {
    const token = searchParams?.get("token");
    const firstUser =
      searchParams?.get("first_user") === "true" && NEXT_PUBLIC_CLOUD_ENABLED;
    if (!token) {
      setError(t("verifyEmail.missingToken.error"));
      return;
    }

    const response = await fetch("/api/auth/verify", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ token }),
    });

    if (response.ok) {
      // Redirect to login page instead of /app so user can log in
      // from any browser (not dependent on the original signup session)
      const loginUrl = firstUser
        ? "/auth/login?verified=true&first_user=true"
        : "/auth/login?verified=true";
      window.location.href = loginUrl;
    } else {
      let errorDetail = t("verifyEmail.unknownError.text");
      try {
        errorDetail = (await response.json()).detail;
      } catch (e) {
        console.error("Failed to parse verification error response:", e);
      }
      setError(t("verifyEmail.verificationFailed.error", { errorDetail }));
    }
  }, [searchParams, t]);

  useEffect(() => {
    verify();
  }, [verify]);

  return (
    <main>
      <div className="min-h-screen flex flex-col items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
        <Logo folded size={64} className="mx-auto w-fit animate-pulse" />
        {!error ? (
          <>
            <Spacer rem={0.5} />
            <Text as="p">{t("verifyEmail.verifying.text")}</Text>
          </>
        ) : (
          <div>
            <Spacer rem={0.5} />
            <Text as="p">{error}</Text>

            {user && (
              <div className="text-center">
                <RequestNewVerificationEmail email={user.email}>
                  {/* TODO(@raunakab): migrate to @opal/components Text */}
                  <p className="text-sm mt-2 text-link">
                    {t("verifyEmail.getNewEmailLink.label")}
                  </p>
                </RequestNewVerificationEmail>
              </div>
            )}
          </div>
        )}
      </div>
    </main>
  );
}
