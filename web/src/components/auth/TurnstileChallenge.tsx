"use client";

import { useEffect, useRef, useState } from "react";

interface TurnstileChallengeProps {
  siteKey: string;
  onVerified: () => void;
  onError?: (message: string) => void;
}

interface TurnstileAPI {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      callback: (token: string) => void;
      "error-callback"?: (code: string) => void;
      "expired-callback"?: () => void;
      theme?: "light" | "dark" | "auto";
      size?: "normal" | "flexible" | "compact" | "invisible";
    }
  ) => string;
  reset: (widgetId?: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileAPI;
  }
}

const TURNSTILE_SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js";

// Loads the Turnstile widget, submits the resulting token to the backend to
// set a signed HttpOnly cookie, and only then calls onVerified. Gates the
// signup form + OAuth button so a user cannot proceed until the challenge
// succeeds.
export default function TurnstileChallenge({
  siteKey,
  onVerified,
  onError,
}: TurnstileChallengeProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [scriptReady, setScriptReady] = useState(false);

  useEffect(() => {
    if (
      typeof document === "undefined" ||
      document.querySelector(`script[src="${TURNSTILE_SCRIPT_SRC}"]`)
    ) {
      if (window.turnstile) setScriptReady(true);
      return;
    }
    const script = document.createElement("script");
    script.src = TURNSTILE_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.onload = () => setScriptReady(true);
    script.onerror = () => onError?.("Failed to load challenge widget");
    document.head.appendChild(script);
  }, [onError]);

  useEffect(() => {
    if (!scriptReady || !window.turnstile || !containerRef.current) return;
    const container = containerRef.current;

    async function submitToken(token: string) {
      try {
        const res = await fetch("/api/auth/turnstile/verify", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          onError?.(body.detail ?? "Verification failed. Try again.");
          window.turnstile?.reset(widgetIdRef.current ?? undefined);
          return;
        }
        onVerified();
      } catch {
        onError?.("Verification request failed. Try again.");
        window.turnstile?.reset(widgetIdRef.current ?? undefined);
      }
    }

    widgetIdRef.current = window.turnstile.render(container, {
      sitekey: siteKey,
      callback: (token: string) => void submitToken(token),
      "error-callback": (code: string) => onError?.(`Challenge error: ${code}`),
      "expired-callback": () =>
        window.turnstile?.reset(widgetIdRef.current ?? undefined),
      theme: "auto",
    });
  }, [scriptReady, siteKey, onVerified, onError]);

  return <div ref={containerRef} className="flex justify-center w-full" />;
}
