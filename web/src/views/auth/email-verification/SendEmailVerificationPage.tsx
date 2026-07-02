"use client";

import { useEffect } from "react";
import { redirect, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { PageLoader } from "@/refresh-components/PageLoader";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { requestEmailVerification } from "@/lib/auth/svc";
import { toast } from "@/hooks/useToast";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";

export default function SendEmailVerificationPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  // Resend flow: fire-and-forget, then strip the ?resend param.
  useEffect(() => {
    if (!searchParams.get("resend") || !user) return;
    router.replace("/auth/send-email-verification" as Route);
    requestEmailVerification(user.email).then((response) => {
      if (response.ok) {
        toast.success("Verification email resent!");
      } else {
        response
          .json()
          .then((body) =>
            toast.error(`Failed to resend verification email — ${body.detail}`)
          );
      }
    });
  }, [searchParams, user, router]);

  if (isLoading) return <PageLoader />;
  if (!user) redirect("/auth/login");
  if (user.is_verified || !authTypeMetadata.requiresVerification)
    redirect("/app");

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      description="We've sent a verification link to your email address."
      bottomPrompt={backToLoginOrSignupCopy()}
      logoSrc={logoUrl}
    >
      <AuthLayouts.Message
        title={`Email sent to ${user.email}`}
        description={markdown(
          "Didn't receive an email? [Resend](/auth/send-email-verification?resend=true)"
        )}
      />
    </AuthLayouts.Card>
  );
}
