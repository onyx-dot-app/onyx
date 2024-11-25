"use client";

import { HealthCheckBanner } from "@/components/health/healthcheck";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Text from "@/components/ui/text";
import { RequestNewVerificationEmail } from "../waiting-on-verification/RequestNewVerificationEmail";
import { User } from "@/lib/types";
import { Logo } from "@/components/Logo";

export function Verify({ user }: { user: User | null }) {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [error, setError] = useState("");

  const verify = useCallback(async () => {
    const token = searchParams.get("token");
    if (!token) {
      setError(
        "Missing verification token. Try requesting a new verification email."
      );
      return;
    }

    const response = await fetch("/api/auth/verify", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ token }),
    });

    if (response.ok) {
      router.push("/");
    } else {
      const errorDetail = (await response.json()).detail;
      setError(
        `Failed to verify your email - ${errorDetail}. Please try requesting a new verification email.`
      );
    }
  }, [searchParams, router]);

  useEffect(() => {
    verify();
  }, [verify]);

  return (
    <main>
      <div className="absolute top-10x w-full">
        <HealthCheckBanner />
      </div>
      <div className="min-h-screen flex items-center justify-center py-12 px-4 sm:px-6 lg:px-8">
        <div>
          <Logo
            height={64}
            width={64}
            className="mx-auto w-fit animate-pulse"
          />

          {!error ? (
            <Text className="mt-2">Verifying your email...</Text>
          ) : (
            <div>
              <Text className="mt-2">{error}</Text>

              {user && (
                <div className="text-center">
                  <RequestNewVerificationEmail email={user.email}>
                    <Text className="mt-2 text-link">
                      Get new verification email
                    </Text>
                  </RequestNewVerificationEmail>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
