"use client";

import { useEffect } from "react";
import { useSearchParams } from "next/navigation";
import { useAuthTypeMetadata, useAuthRedirect } from "@/lib/auth/hooks";
import { useSettings } from "@/lib/settings/hooks";
import { AuthLayouts } from "@opal/layouts";
import { toast } from "@/hooks/useToast";
import EmailPasswordForm from "@/sections/auth/EmailPasswordForm";
import { markdown } from "@opal/utils";
import { createAccountCardCopy } from "@/lib/auth/copies";

export default function SignupPage() {
  const searchParams = useSearchParams();
  const nextUrl = searchParams.get("next");
  const defaultEmail = searchParams.get("email");
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl, appName } = useSettings();

  useAuthRedirect("signup");

  useEffect(() => {
    const error = searchParams.get("error");
    if (error) {
      toast.error(
        error === "Anonymous"
          ? "Your team does not have anonymous access enabled."
          : "An error occurred."
      );
    }
  }, [searchParams]);

  return (
    <AuthLayouts.Card
      {...createAccountCardCopy(appName)}
      bottomPrompt={markdown(
        "Already have an account? [Sign In](/auth/login?autoRedirectToSignup=false)"
      )}
      logoSrc={logoUrl}
    >
      <EmailPasswordForm
        label="create"
        shouldVerify={authTypeMetadata.requiresVerification}
        nextUrl={nextUrl}
        defaultEmail={defaultEmail}
      />
    </AuthLayouts.Card>
  );
}
