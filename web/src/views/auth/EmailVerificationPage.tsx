"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { Text } from "@opal/components";
import { markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { requestEmailVerification, verifyEmail } from "@/lib/auth/svc";
import RequestNewVerificationEmail from "@/sections/auth/RequestNewVerificationEmail";
import { toast } from "@/hooks/useToast";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { redirect } from "next/navigation";

export default function EmailVerificationPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  const token = searchParams.get("token");
  const firstUser =
    searchParams.get("first_user") === "true" && NEXT_PUBLIC_CLOUD_ENABLED;

  const [verifyError, setVerifyError] = useState("");

  // Token flow: process the verification link from the email.
  const verify = useCallback(async () => {
    if (!token) return;
    try {
      await verifyEmail(token);
      const loginUrl = firstUser
        ? "/auth/login?verified=true&first_user=true"
        : "/auth/login?verified=true";
      window.location.href = loginUrl;
    } catch (e) {
      setVerifyError(
        `Failed to verify your email — ${e instanceof Error ? e.message : "unknown error"}. Please request a new verification email.`
      );
    }
  }, [token, firstUser]);

  useEffect(() => {
    verify();
  }, [verify]);

  // Waiting flow: redirect to /app if already verified.
  useEffect(() => {
    if (!token) {
      if (user === undefined) return;
      if (!authTypeMetadata.requiresVerification || user?.is_verified) {
        router.replace("/app" as Route);
      }
    }
  }, [token, user, authTypeMetadata.requiresVerification, router]);

  // Resend flow: fire-and-forget, then strip the ?resend param.
  useEffect(() => {
    if (!token && searchParams.get("resend") && user) {
      router.replace("/auth/email-verification" as Route);
      requestEmailVerification(user.email).then((response) => {
        if (response.ok) {
          toast.success("Verification email resent!");
        } else {
          response
            .json()
            .then((body) =>
              toast.error(
                `Failed to resend verification email — ${body.detail}`
              )
            );
        }
      });
    }
  }, [token, searchParams, user, router]);

  if (!user && !token) redirect("/auth/login");

  if (token) {
    return (
      <AuthLayouts.Card title="Verify Email" logoSrc={logoUrl}>
        {!verifyError ? (
          <Text font="main-ui-body" color="text-03">
            Verifying your email...
          </Text>
        ) : (
          <div className="flex flex-col gap-2">
            <Text font="main-ui-body" color="text-03">
              {verifyError}
            </Text>
            {user && (
              <RequestNewVerificationEmail email={user.email}>
                Get new verification email
              </RequestNewVerificationEmail>
            )}
          </div>
        )}
      </AuthLayouts.Card>
    );
  }

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      logoSrc={logoUrl}
      description="We've sent a verification link to your email address."
      bottomPrompt={markdown(
        "Back to [Sign In](/auth/login) or [Create an Account](/auth/signup)"
      )}
    >
      <AuthLayouts.Message
        title={user ? `Email sent to ${user.email}` : "Redirecting..."}
        description={markdown(
          "Didn't receive an email? [Resend](/auth/email-verification?resend=true)"
        )}
      />
    </AuthLayouts.Card>
  );
}
