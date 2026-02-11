/**
 * Hook for Google reCAPTCHA v2 checkbox integration.
 *
 * Usage:
 * 1. Add NEXT_PUBLIC_RECAPTCHA_V2_SITE_KEY to your environment
 * 2. Use the hook to render a captcha widget and get the token
 *
 * Example:
 * ```tsx
 * const { isCaptchaEnabled, isLoaded, token, renderCaptcha, resetCaptcha } = useCaptchaV2();
 *
 * useEffect(() => {
 *   if (isCaptchaEnabled && isLoaded) {
 *     renderCaptcha("captcha-container");
 *   }
 * }, [isCaptchaEnabled, isLoaded, renderCaptcha]);
 *
 * // In JSX:
 * {isCaptchaEnabled && <div id="captcha-container" />}
 * <button disabled={isCaptchaEnabled && !token}>Submit</button>
 * ```
 */

import { useCallback, useEffect, useState, useRef } from "react";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

const RECAPTCHA_V2_SITE_KEY =
  process.env.NEXT_PUBLIC_RECAPTCHA_V2_SITE_KEY || "";

export function useCaptchaV2() {
  const [isLoaded, setIsLoaded] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const widgetIdRef = useRef<number | null>(null);

  // Only enabled for cloud deployments with key configured
  const isCaptchaEnabled =
    NEXT_PUBLIC_CLOUD_ENABLED && Boolean(RECAPTCHA_V2_SITE_KEY);

  useEffect(() => {
    if (!isCaptchaEnabled) {
      return;
    }

    const scriptSrc =
      "https://www.google.com/recaptcha/api.js?onload=onRecaptchaV2Load&render=explicit";

    // Check if already loaded
    if (window.grecaptcha?.render) {
      setIsLoaded(true);
      return;
    }

    // Check if script already exists
    const existingScript = document.querySelector(`script[src="${scriptSrc}"]`);
    if (existingScript) {
      existingScript.addEventListener("load", () => {
        if (window.grecaptcha?.ready) {
          window.grecaptcha.ready(() => setIsLoaded(true));
        } else {
          setIsLoaded(true);
        }
      });
      return;
    }

    window.onRecaptchaV2Load = () => {
      if (window.grecaptcha?.ready) {
        window.grecaptcha.ready(() => setIsLoaded(true));
      } else {
        setIsLoaded(true);
      }
    };

    const script = document.createElement("script");
    script.src = scriptSrc;
    script.async = true;
    script.defer = true;
    document.head.appendChild(script);

    return () => {
      window.onRecaptchaV2Load = undefined;
    };
  }, [isCaptchaEnabled]);

  const renderCaptcha = useCallback(
    (containerId: string) => {
      if (!isLoaded || !isCaptchaEnabled || widgetIdRef.current !== null) {
        return;
      }

      const container = document.getElementById(containerId);
      if (!container || !window.grecaptcha?.render) {
        return;
      }

      const id = window.grecaptcha.render(containerId, {
        sitekey: RECAPTCHA_V2_SITE_KEY,
        callback: (response: string) => setToken(response),
        "expired-callback": () => setToken(null),
        "error-callback": () => setToken(null),
      });
      widgetIdRef.current = id;
    },
    [isLoaded, isCaptchaEnabled]
  );

  const resetCaptcha = useCallback(() => {
    if (widgetIdRef.current !== null && window.grecaptcha) {
      window.grecaptcha.reset(widgetIdRef.current);
      setToken(null);
    }
  }, []);

  return {
    isCaptchaEnabled,
    isLoaded,
    token,
    renderCaptcha,
    resetCaptcha,
  };
}
