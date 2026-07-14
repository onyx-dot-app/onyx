"use client";

import { useEffect } from "react";
import { redirect, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { PageLoader } from "@/refresh-components/PageLoader";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { requestEmailVerification } from "@/lib/auth/svc";
import { logout } from "@/lib/users/svc";
import { toast } from "@/hooks/useToast";
import { Logo } from "@/lib/app/components";

export default function SendEmailVerificationPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading, mutateUser } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();

  // Redirect immediately when the verification tab signals success.
  useEffect(() => {
    const channel = new BroadcastChannel("email-verification");
    channel.onmessage = () => router.replace("/app" as Route);
    return () => channel.close();
  }, [router]);

  // Poll as a fallback in case the BroadcastChannel message is missed
  // (e.g. the verification happened in a different browser or device).
  useEffect(() => {
    const interval = setInterval(() => mutateUser(), 3000);
    return () => clearInterval(interval);
  }, [mutateUser]);

  // Resend flow: fire-and-forget, then strip the ?resend param.
  useEffect(() => {
    const emailForResend = user?.email ?? searchParams.get("email");
    if (!searchParams.get("resend") || !emailForResend) return;
    const base = `/auth/send-email-verification${emailForResend ? `?email=${encodeURIComponent(emailForResend)}` : ""}`;
    router.replace(base as Route);
    requestEmailVerification(emailForResend)
      .then(() => toast.success("Verification email resent!"))
      .catch((e: Error) =>
        toast.error(
          `Failed to resend verification email — ${e.message || "unknown error"}`
        )
      );
  }, [searchParams, user, router]);

  async function handleLogout() {
    await logout();
    router.replace("/auth/login" as Route);
  }

  const emailParam = searchParams.get("email");
  const displayEmail = user?.email ?? emailParam;

  if (isLoading) return <PageLoader />;
  if (!displayEmail) redirect("/auth/login");
  if (user?.is_verified || !authTypeMetadata?.requiresVerification)
    redirect("/app");

  const resendUrl = `/auth/send-email-verification?resend=true${emailParam ? `&email=${encodeURIComponent(emailParam)}` : ""}`;

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      description="We've sent a verification link to your email address."
      icon={Logo}
    >
      <AuthLayouts.Message
        title={`Email sent to ${displayEmail}`}
        description={markdown(
          `Didn't receive an email? [Resend](${resendUrl})`
        )}
      />
      <AuthLayouts.OrSeparator />
      <AuthLayouts.Submit label="logout" onClick={handleLogout} />
    </AuthLayouts.Card>
  );
}
