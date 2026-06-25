"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { Text } from "@opal/components";
import { markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/hooks/useCurrentUser";
import { useAuthTypeMetadata } from "@/hooks/useAuthTypeMetadata";
import RequestNewVerificationEmail from "@/sections/auth/RequestNewVerificationEmail";

export default function WaitingOnVerificationPage() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { authTypeMetadata } = useAuthTypeMetadata();
  const { logoUrl } = useSettings();

  // useEffect(() => {
  //   if (!user) {
  //     router.replace("/auth/login" as Route);
  //     return;
  //   }

  //   if (!authTypeMetadata.requiresVerification || user.is_verified) {
  //     router.replace("/app" as Route);
  //   }
  // }, [user, authTypeMetadata, router]);

  // if (!user) return null;

  return (
    <AuthLayouts.Card
      title="Check your inbox"
      logoSrc={logoUrl}
      description="We’ve sent a verification link to your email address."
    >
      <AuthLayouts.Message
        title={`Email sent to ${user?.email}`}
        description={markdown(
          "Didn't receive an email? [Resend](/link-here-???)"
        )}
      />
    </AuthLayouts.Card>
  );
}
