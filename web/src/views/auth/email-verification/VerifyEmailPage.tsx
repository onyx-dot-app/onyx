"use client";

import { useState, useEffect, useRef } from "react";
import { redirect, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { verifyEmail } from "@/lib/auth/svc";
import { toast } from "@/hooks/useToast";
import { welcomeCardCopy } from "@/lib/auth/copies";

export default function VerifyEmailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading } = useCurrentUser();
  const { appName, logoUrl } = useSettings();

  const token = searchParams.get("token");
  const verifyingRef = useRef(false);
  const [verified, setVerified] = useState(false);

  // Token flow: wait for auth state to settle, then verify once.
  useEffect(() => {
    if (!token || isLoading || verifyingRef.current) return;
    verifyingRef.current = true;
    verifyEmail(token)
      .then(() => setVerified(true))
      .catch((e) => {
        toast.error(
          `Failed to verify your email — ${e instanceof Error ? e.message : "unknown error"}.`
        );
        router.replace((user ? "/app" : "/auth/login") as Route);
      });
  }, [token, isLoading, user, router]);

  if (!token) redirect("/auth/send-email-verification");

  return (
    <AuthLayouts.Card {...welcomeCardCopy(appName)} logoSrc={logoUrl}>
      {verified ? (
        <AuthLayouts.Message
          messageType="success"
          title="Verification successful"
          description={markdown(
            "Your email has been successfully verified. You can now close this tab, or [continue to the app](/app)."
          )}
        />
      ) : (
        <AuthLayouts.Message
          title="Verifying your token..."
          description="Give us a quick moment while we finish verifying your token."
        />
      )}
    </AuthLayouts.Card>
  );
}
