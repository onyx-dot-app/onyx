"use client";

import { ReactNode, useCallback, useState } from "react";
import TurnstileChallenge from "./TurnstileChallenge";
import Text from "@/refresh-components/texts/Text";

interface SignupChallengeGateProps {
  siteKey: string;
  children: ReactNode;
}

// Wraps the signup form + OAuth button. If a Turnstile site key is
// configured, the child UI is only revealed after the user completes the
// challenge and the backend cookie is set. When siteKey is empty, children
// render immediately (self-hosted / dev / deployments without Turnstile).
export default function SignupChallengeGate({
  siteKey,
  children,
}: SignupChallengeGateProps) {
  const [verified, setVerified] = useState(!siteKey);
  const [error, setError] = useState<string | null>(null);

  // useCallback on both handlers keeps the props referentially stable across
  // re-renders. Without this, TurnstileChallenge's useEffect would re-run
  // every time setError bumps parent state, rendering a new widget on top of
  // the old one — including after stopWidget() has tried to stop rendering.
  const handleVerified = useCallback(() => {
    setError(null);
    setVerified(true);
  }, []);
  const handleError = useCallback((message: string) => {
    setError(message);
  }, []);

  if (!siteKey || verified) {
    return <>{children}</>;
  }

  return (
    <div className="flex flex-col items-center w-full gap-4">
      <Text as="p" text03 mainUiBody>
        Verify you&apos;re a human to continue.
      </Text>
      <TurnstileChallenge
        siteKey={siteKey}
        onVerified={handleVerified}
        onError={handleError}
      />
      {error && (
        <Text as="p" mainUiMuted className="text-status-error-05">
          {error}
        </Text>
      )}
    </div>
  );
}
