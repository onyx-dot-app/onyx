"use client";

import { useEffect, useRef } from "react";
import { redirect, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { verifyEmail } from "@/lib/auth/svc";
import { toast } from "@/hooks/useToast";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

export default function VerifyEmailPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user, isLoading } = useCurrentUser();
  const { logoUrl } = useSettings();

  const token = searchParams.get("token");
  const firstUser =
    searchParams.get("first_user") === "true" && NEXT_PUBLIC_CLOUD_ENABLED;

  const verifyingRef = useRef(false);

  // Token flow: wait for auth state to settle, then verify once.
  useEffect(() => {
    if (!token || isLoading || verifyingRef.current) return;
    verifyingRef.current = true;
    verifyEmail(token)
      .then(() => {
        if (user) {
          router.replace("/app" as Route);
        } else {
          router.replace(
            (firstUser
              ? "/auth/login?verified=true&first_user=true"
              : "/auth/login?verified=true") as Route
          );
        }
      })
      .catch((e) => {
        toast.error(
          `Failed to verify your email — ${e instanceof Error ? e.message : "unknown error"}.`
        );
        if (user) {
          router.replace("/app" as Route);
        } else {
          router.replace("/auth/login" as Route);
        }
      });
  }, [token, isLoading, user, firstUser, router]);

  if (!token) redirect("/auth/send-email-verification");

  return (
    <AuthLayouts.Card title="Verify Email" logoSrc={logoUrl}>
      <AuthLayouts.Message
        title="Verifying your token..."
        description="Give us a quick moment while we finish verifying your token."
      />
    </AuthLayouts.Card>
  );
}
