"use client";

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { Text } from "@opal/components";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import { RequestNewVerificationEmail } from "@/sections/auth/RequestNewVerificationEmail";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

export default function VerifyEmailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  const [error, setError] = useState("");

  useEffect(() => {
    if (user === undefined) return;
    if (!authTypeMetadata.requiresVerification || user?.is_verified) {
      router.replace("/app" as Route);
    }
  }, [user, authTypeMetadata.requiresVerification, router]);

  const verify = useCallback(async () => {
    const token = searchParams?.get("token");
    const firstUser =
      searchParams?.get("first_user") === "true" && NEXT_PUBLIC_CLOUD_ENABLED;
    if (!token) {
      setError(
        "Missing verification token. Try requesting a new verification email."
      );
      return;
    }

    const response = await fetch("/api/auth/verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token }),
    });

    if (response.ok) {
      const loginUrl = firstUser
        ? "/auth/login?verified=true&first_user=true"
        : "/auth/login?verified=true";
      window.location.href = loginUrl;
    } else {
      let errorDetail = "unknown error";
      try {
        errorDetail = (await response.json()).detail;
      } catch (e) {
        console.error("Failed to parse verification error response:", e);
      }
      setError(
        `Failed to verify your email - ${errorDetail}. Please try requesting a new verification email.`
      );
    }
  }, [searchParams]);

  useEffect(() => {
    verify();
  }, [verify]);

  return (
    <AuthLayouts.Card title="Verify Email" logoSrc={logoUrl}>
      {!error ? (
        <Text font="main-ui-body" color="text-03">
          Verifying your email...
        </Text>
      ) : (
        <div className="flex flex-col gap-2">
          <Text font="main-ui-body" color="text-03">
            {error}
          </Text>
          {user && (
            <div className="text-center">
              <RequestNewVerificationEmail email={user.email}>
                <Text font="main-ui-body" color="text-03">
                  Get new verification email
                </Text>
              </RequestNewVerificationEmail>
            </div>
          )}
        </div>
      )}
    </AuthLayouts.Card>
  );
}
