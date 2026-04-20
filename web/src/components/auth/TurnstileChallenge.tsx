"use client";

import { useEffect, useRef, useState } from "react";

interface TurnstileChallengeProps {
  siteKey: string;
  onVerified: () => void;
  onError?: (message: string) => void;
  // Stop auto-resetting the widget after this many consecutive failures.
  // Prevents an always-fail key from looping siteverify calls forever.
  maxAttempts?: number;
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
  remove: (widgetId?: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileAPI;
  }
}

const TURNSTILE_SCRIPT_SRC =
  "https://challenges.cloudflare.com/turnstile/v0/api.js";

const DEFAULT_MAX_ATTEMPTS = 3;

// Cloudflare Turnstile widget error codes → plain-language messages.
// Full code list: https://developers.cloudflare.com/turnstile/troubleshooting/client-side-errors/error-codes/
function humanizeTurnstileError(code: string): string {
  const normalized = code.trim();
  if (normalized.startsWith("300") || normalized.startsWith("600")) {
    return "Couldn't reach the challenge service. Check your connection and try again.";
  }
  if (normalized.startsWith("400")) {
    return "Challenge couldn't load. Refresh the page or contact support if this keeps happening.";
  }
  return "Verification failed. Please try again.";
}

// Loads the Turnstile widget, submits the resulting token to the backend to
// set a signed HttpOnly cookie, and only then calls onVerified. After
// maxAttempts consecutive failures the widget is permanently removed and
// the user is told to refresh — prevents an always-fail sitekey/secret
// pair from spinning siteverify calls forever.
export default function TurnstileChallenge({
  siteKey,
  onVerified,
  onError,
  maxAttempts = DEFAULT_MAX_ATTEMPTS,
}: TurnstileChallengeProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const attemptsRef = useRef<number>(0);
  const stoppedRef = useRef<boolean>(false);
  const [scriptReady, setScriptReady] = useState(false);

  useEffect(() => {
    if (typeof document === "undefined") return;

    // Another instance of this component may have already started loading the
    // script. If it's still in-flight we need to listen for its load event;
    // if it already finished we can flip scriptReady immediately. Without
    // this handshake the second mount sees the existing tag and bails,
    // leaving scriptReady stuck at false forever.
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${TURNSTILE_SCRIPT_SRC}"]`
    );
    if (existing) {
      if (window.turnstile) {
        setScriptReady(true);
      } else {
        const onExistingLoad = () => setScriptReady(true);
        existing.addEventListener("load", onExistingLoad, { once: true });
        return () => existing.removeEventListener("load", onExistingLoad);
      }
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

    function stopWidget() {
      stoppedRef.current = true;
      if (widgetIdRef.current && window.turnstile) {
        try {
          window.turnstile.remove(widgetIdRef.current);
        } catch {
          // ignore — widget may already be gone
        }
        widgetIdRef.current = null;
      }
    }

    function recordFailureAndRetry(userMessage: string) {
      attemptsRef.current += 1;
      if (attemptsRef.current >= maxAttempts) {
        onError?.("Too many failed attempts. Refresh the page to try again.");
        stopWidget();
        return;
      }
      onError?.(userMessage);
      window.turnstile?.reset(widgetIdRef.current ?? undefined);
    }

    async function submitToken(token: string) {
      if (stoppedRef.current) return;
      try {
        const res = await fetch("/api/auth/turnstile/verify", {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ token }),
        });
        if (!res.ok) {
          const body = await res.json().catch(() => ({}));
          // eslint-disable-next-line no-console
          console.warn(
            `Turnstile verify rejected: ${body.detail ?? res.status}`
          );
          recordFailureAndRetry("Verification failed. Please try again.");
          return;
        }
        onVerified();
      } catch (exc) {
        // eslint-disable-next-line no-console
        console.warn("Turnstile verify request failed", exc);
        recordFailureAndRetry(
          "Couldn't reach the verification service. Try again."
        );
      }
    }

    widgetIdRef.current = window.turnstile.render(container, {
      sitekey: siteKey,
      callback: (token: string) => void submitToken(token),
      "error-callback": (code: string) => {
        // eslint-disable-next-line no-console
        console.warn(`Turnstile widget error (code ${code})`);
        // Widget-side errors count toward the retry cap too — a bad sitekey
        // or domain mismatch would otherwise loop forever.
        attemptsRef.current += 1;
        if (attemptsRef.current >= maxAttempts) {
          onError?.("Too many failed attempts. Refresh the page to try again.");
          stopWidget();
          return;
        }
        onError?.(humanizeTurnstileError(code));
      },
      "expired-callback": () =>
        window.turnstile?.reset(widgetIdRef.current ?? undefined),
      theme: "auto",
    });
  }, [scriptReady, siteKey, onVerified, onError, maxAttempts]);

  return <div ref={containerRef} className="flex justify-center w-full" />;
}
