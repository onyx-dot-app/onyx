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

  // Poll only when a session exists — pointless without one.
  useEffect(() => {
    if (!user) return;
    const interval = setInterval(() => mutateUser(), 3000);
    return () => clearInterval(interval);
  }, [user, mutateUser]);

  const email = searchParams.get("email");

  // Resend flow: fire-and-forget, then strip the ?resend param.
  useEffect(() => {
    if (!searchParams.get("resend") || !email) return;
    router.replace(
      `/auth/send-email-verification?email=${encodeURIComponent(email)}` as Route
    );
    requestEmailVerification(email)
      .then(() => toast.success("Verification email resent!"))
      .catch((e: Error) =>
        toast.error(
          `Failed to resend verification email — ${e.message || "unknown error"}`
        )
      );
  }, [searchParams, email, router]);

  async function handleLogout() {
    await logout();
    router.replace("/auth/login" as Route);
  }

  // Wait for auth state before potentially skipping verified users to /app.
  if (isLoading) return <PageLoader />;
  if (!email) redirect("/auth/login");
  if (user?.is_verified || !authTypeMetadata?.requiresVerification)
    redirect("/app");

  const resendUrl = `/auth/send-email-verification?resend=true&email=${encodeURIComponent(email)}`;

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      description="We've sent a verification link to your email address."
      icon={Logo}
    >
      <AuthLayouts.Message
        title={`Email sent to ${email}`}
        description={markdown(
          `Didn't receive an email? [Resend](${resendUrl})`
        )}
      />
      {user && (
        <>
          <AuthLayouts.OrSeparator />
          <AuthLayouts.Submit label="logout" onClick={handleLogout} />
        </>
      )}
    </AuthLayouts.Card>
  );
}
