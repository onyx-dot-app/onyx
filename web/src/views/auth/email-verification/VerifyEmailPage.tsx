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
import { AUTH_SUCCESS_REDIRECT_DELAY_MS } from "@/lib/auth/constants";
import { backToLoginOrSignupCopy, welcomeCardCopy } from "@/lib/auth/copies";
import { Logo } from "@/lib/app/components";

export default function VerifyEmailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading } = useCurrentUser();
  const { appName } = useSettings();

  const token = searchParams.get("token");
  const verifyingRef = useRef(false);
  const [verified, setVerified] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(
    AUTH_SUCCESS_REDIRECT_DELAY_MS / 1000
  );

  // Token flow: wait for auth state to settle, then verify once.
  useEffect(() => {
    if (!token || isLoading || verifyingRef.current) return;
    verifyingRef.current = true;
    verifyEmail(token)
      .then(() => {
        const channel = new BroadcastChannel("email-verification");
        channel.postMessage("verified");
        channel.close();
        setVerified(true);
      })
      .catch((e) => {
        toast.error(
          `Failed to verify your email — ${e instanceof Error ? e.message : "unknown error"}.`
        );
        router.replace((user ? "/app" : "/auth/login") as Route);
      });
  }, [token, isLoading, user, router]);

  useEffect(() => {
    if (!verified) return;
    const destination = (user ? "/app" : "/auth/login") as Route;
    const id = setInterval(
      () => setSecondsLeft((s) => Math.max(0, s - 1)),
      1000
    );
    const timer = setTimeout(
      () => router.replace(destination),
      AUTH_SUCCESS_REDIRECT_DELAY_MS
    );
    return () => {
      clearInterval(id);
      clearTimeout(timer);
    };
  }, [verified, user, router]);

  if (!token) redirect("/auth/send-email-verification");

  return (
    <AuthLayouts.Card
      {...welcomeCardCopy(appName)}
      bottomPrompt={backToLoginOrSignupCopy()}
      icon={Logo}
    >
      {verified ? (
        <AuthLayouts.Message
          messageType="success"
          title="Verification successful"
          description={`Your email has been successfully verified. Redirecting to ${appName} in ${secondsLeft}s or [go there now](/app).`}
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
