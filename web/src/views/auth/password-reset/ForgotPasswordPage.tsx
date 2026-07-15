"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { forgotPassword } from "@/lib/auth/svc";
import { AuthLayouts } from "@opal/layouts";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";
import { markdown } from "@opal/utils";
import { toast } from "@/hooks/useToast";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import type { Route } from "next";
import { Logo } from "@/lib/app/components";
import { redirect } from "next/navigation";
import { useCurrentUser } from "@/lib/users/hooks";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams?.get("email");
  const isResend = searchParams?.get("reset") === "true";
  const { user } = useCurrentUser();

  const firedRef = useRef(false);

  // Initial send — fires once when the page first loads.
  useEffect(() => {
    if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !email) {
      router.replace("/auth/login" as Route);
      return;
    }
    if (firedRef.current) return;
    firedRef.current = true;
    forgotPassword(email).catch((e) =>
      console.error("Failed to send password reset email:", e)
    );
  }, [email, router]);

  // Redirect to login once the reset is completed in another tab.
  useEffect(() => {
    const channel = new BroadcastChannel("password-reset");
    channel.onmessage = () => router.replace("/auth/login" as Route);
    return () => channel.close();
  }, [router]);

  // Resend — fires whenever ?reset=true is present, then strips the param.
  useEffect(() => {
    if (!isResend || !email) return;
    router.replace(
      `/auth/forgot-password?email=${encodeURIComponent(email)}` as Route
    );
    forgotPassword(email)
      .then(() => toast.success("Email resent!"))
      .catch((e) => console.error("Failed to resend password reset email:", e));
  }, [isResend, email, router]);

  if (user) redirect("/app");
  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !email) return null;

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      description="We’ve sent a password reset link to your email address."
      bottomPrompt={backToLoginOrSignupCopy()}
      icon={Logo}
    >
      <AuthLayouts.Message
        title={`Email sent to ${email}.`}
        description={markdown(
          `Didn't receive the email? [Resend](/auth/forgot-password?email=${encodeURIComponent(email)}&reset=true)`
        )}
      />
    </AuthLayouts.Card>
  );
}
