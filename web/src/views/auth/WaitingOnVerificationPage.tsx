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

  useEffect(() => {
    if (user === undefined) return;

    if (!user) {
      router.replace("/auth/login" as Route);
      return;
    }

    if (!authTypeMetadata.requiresVerification || user.is_verified) {
      router.replace("/app" as Route);
    }
  }, [user, authTypeMetadata, router]);

  if (!user) return null;

  return (
    <AuthLayouts.Card title="Verify your email" logoSrc={logoUrl}>
      <div className="flex flex-col gap-2">
        <Text font="main-ui-body" color="text-03">
          {markdown(
            `Hey, *${user.email}*, it looks like you haven't verified your email yet.\nCheck your inbox for an email from us to get started!`
          )}
        </Text>
        <RequestNewVerificationEmail email={user.email}>
          Resend verification email
        </RequestNewVerificationEmail>
      </div>
    </AuthLayouts.Card>
  );
}
