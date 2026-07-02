"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { forgotPassword } from "@/lib/auth/svc";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import type { Route } from "next";

export default function ForgotPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const email = searchParams?.get("email");
  const { logoUrl } = useSettings();

  useEffect(() => {
    if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !email) {
      router.replace("/auth/login" as Route);
      return;
    }
    forgotPassword(email).catch(() => {});
  }, [email, router]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !email) return null;

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      description={`We sent a password reset link to ${email}.`}
      bottomPrompt={backToLoginOrSignupCopy()}
      logoSrc={logoUrl}
    >
      <AuthLayouts.Message
        title="Link sent."
        description="If that address is registered, you'll receive an email shortly. Check your spam folder if it doesn't arrive within a few minutes."
      />
    </AuthLayouts.Card>
  );
}
