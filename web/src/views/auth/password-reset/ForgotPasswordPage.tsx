"use client";

import { useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { forgotPassword } from "@/lib/auth/svc";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";
import { markdown } from "@opal/utils";
import { toast } from "@/hooks/useToast";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import type { Route } from "next";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams?.get("email");
  const isResend = searchParams?.get("reset") === "true";
  const { logoUrl } = useSettings();

  const firedRef = useRef(false);

  // Initial send — fires once when the page first loads.
  useEffect(() => {
    if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !email) {
      router.replace("/auth/login" as Route);
      return;
    }
    if (firedRef.current) return;
    firedRef.current = true;
    forgotPassword(email).catch(() => {});
  }, [email, router]);

  // Resend — fires whenever ?reset=true is present, then strips the param.
  useEffect(() => {
    if (!isResend || !email) return;
    router.replace(
      `/auth/forgot-password?email=${encodeURIComponent(email)}` as Route
    );
    forgotPassword(email)
      .then(() => toast.success("Email resent!"))
      .catch(() => {});
  }, [isResend, email, router]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !email) return null;

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      description="We’ve sent a password reset link to your email address."
      bottomPrompt={backToLoginOrSignupCopy()}
      logoSrc={logoUrl}
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
