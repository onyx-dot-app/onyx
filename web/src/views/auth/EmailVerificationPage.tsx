"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/lib/auth/hooks";
import { requestEmailVerification } from "@/lib/auth/svc";
import { toast } from "@/hooks/useToast";

export default function EmailVerificationPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  useEffect(() => {
    if (user === undefined) return;

    if (!user) {
      router.replace("/auth/login" as Route);
      return;
    }

    if (searchParams.get("resend")) {
      router.replace("/auth/email-verification" as Route);
      requestEmailVerification(user.email).then((response) => {
        if (response.ok) {
          toast.success("Verification email resent!");
        } else {
          response
            .json()
            .then((body) =>
              toast.error(
                `Failed to resend verification email - ${body.detail}`
              )
            );
        }
      });
      return;
    }

    if (!authTypeMetadata.requiresVerification || user.is_verified) {
      router.replace("/app" as Route);
    }
  }, [user, authTypeMetadata, router, searchParams]);

  if (!user) return null;

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
        title={`Email sent to ${user.email}`}
        description={markdown(
          "Didn't receive an email? [Resend](/auth/email-verification?resend=true)"
        )}
      />
    </AuthLayouts.Card>
  );
}
