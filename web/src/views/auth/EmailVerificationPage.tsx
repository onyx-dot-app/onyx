"use client";

import { useEffect, useRef } from "react";
import { redirect, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { PageLoader } from "@/refresh-components/PageLoader";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { requestEmailVerification, verifyEmail } from "@/lib/auth/svc";
import { toast } from "@/hooks/useToast";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";

export default function EmailVerificationPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  const token = searchParams.get("token");
  const firstUser =
    searchParams.get("first_user") === "true" && NEXT_PUBLIC_CLOUD_ENABLED;

  const verifyingRef = useRef(false);

  // Token flow: wait for auth state to settle, then verify once.
  useEffect(() => {
    if (!token || isLoading || verifyingRef.current) return;
    verifyingRef.current = true;
    verifyEmail(token)
      .then(() => {
        if (user) {
          router.replace("/app" as Route);
        } else {
          router.replace(
            (firstUser
              ? "/auth/login?verified=true&first_user=true"
              : "/auth/login?verified=true") as Route
          );
        }
      })
      .catch((e) => {
        toast.error(
          `Failed to verify your email — ${e instanceof Error ? e.message : "unknown error"}.`
        );
        if (user) {
          router.replace("/app" as Route);
        } else {
          router.replace("/auth/login" as Route);
        }
      });
  }, [token, isLoading, user, firstUser, router]);

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

  if (isLoading) return <PageLoader />;

  // User is not signed in and has no token that needs verification.
  if (!user && !token) redirect("/auth/login");

  // User is signed in and has not presented a token.
  if (user && !token) {
    // Token is not present because:
    // - user is already verified
    // - OR user does not need verification
    if (user.is_verified || !authTypeMetadata.requiresVerification)
      redirect("/app");

    // Token is not present and needs to be presented first.
    return (
      <AuthLayouts.Card
        title="Check your inbox"
        logoSrc={logoUrl}
        description="We've sent a verification link to your email address."
        bottomPrompt={backToLoginOrSignupCopy()}
      >
        <AuthLayouts.Message
          title={`Email sent to ${user.email}`}
          description={markdown(
            "Didn't receive an email? [Resend](/auth/email-verification?resend=true)"
          )}
        />
      </AuthLayouts.Card>
    );
  }

  // User is or is not signed in (doesn't matter much here) and *HAS* presented a token.
  // In this case, the token should be verified by the `useEffect` hook above.
  //
  // Verification succeeds:
  // - If the user is signed in, then simply redirect to `/app`.
  // - If the user is *NOT* signed in, then redirect to `/auth/login` and prompt the user to sign in first. At this point, the user's email is verified, so all they have to do is log in.
  //
  // Verification fails:
  // - An error should be raised.
  return (
    <AuthLayouts.Card title="Verify Email" logoSrc={logoUrl}>
      <AuthLayouts.Message
        title="Verifying your token..."
        description="Give us a quick moment while we finish verifying your token."
      />
    </AuthLayouts.Card>
  );
}
