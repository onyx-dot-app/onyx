/**
 * Hook for Google reCAPTCHA v3 integration.
 *
 * Usage:
 * 1. Add NEXT_PUBLIC_RECAPTCHA_SITE_KEY to your environment
 * 2. Include the reCAPTCHA script in your page/layout
 * 3. Use the hook to get a captcha token before form submission
 *
 * Example:
 * ```tsx
 * const { getCaptchaToken, isCaptchaEnabled } = useCaptcha();
 *
 * const handleSubmit = async () => {
 *   const token = await getCaptchaToken('signup');
 *   await basicSignup(email, password, referralSource, token);
 * };
 * ```
 */

import { useCallback, useEffect, useState } from "react";

// Declare the global grecaptcha object
declare global {
  interface Window {
    grecaptcha?: {
      ready: (callback: () => void) => void;
      execute: (
        siteKey: string,
        options: { action: string }
      ) => Promise<string>;
    };
  }
}

const RECAPTCHA_SITE_KEY = process.env.NEXT_PUBLIC_RECAPTCHA_SITE_KEY || "";

export function useCaptcha() {
  const [isLoaded, setIsLoaded] = useState(false);

  const isCaptchaEnabled = Boolean(RECAPTCHA_SITE_KEY);

  useEffect(() => {
    if (!isCaptchaEnabled) {
      return;
    }

    const scriptSrc = `https://www.google.com/recaptcha/api.js?render=${RECAPTCHA_SITE_KEY}`;

    // Check if the script is already loaded
    if (window.grecaptcha) {
      window.grecaptcha.ready(() => {
        setIsLoaded(true);
      });
      return;
    }

    // Check if the script is already in the DOM (loading but not yet executed)
    const existingScript = document.querySelector(`script[src="${scriptSrc}"]`);
    if (existingScript) {
      // Script exists but hasn't loaded yet, wait for it
      existingScript.addEventListener("load", () => {
        if (window.grecaptcha) {
          window.grecaptcha.ready(() => {
            setIsLoaded(true);
          });
        }
      });
      return;
    }

    // Load the reCAPTCHA script
    const script = document.createElement("script");
    script.src = scriptSrc;
    script.async = true;
    script.defer = true;

    script.onload = () => {
      if (window.grecaptcha) {
        window.grecaptcha.ready(() => {
          setIsLoaded(true);
        });
      }
    };

    document.head.appendChild(script);

    return () => {
      // Cleanup is tricky with reCAPTCHA, so we leave the script in place
    };
  }, [isCaptchaEnabled]);

  const getCaptchaToken = useCallback(
    async (action: string = "submit"): Promise<string | undefined> => {
      if (!isCaptchaEnabled) {
        return undefined;
      }

      if (!isLoaded || !window.grecaptcha) {
        console.warn("reCAPTCHA not loaded yet");
        return undefined;
      }

      try {
        const token = await window.grecaptcha.execute(RECAPTCHA_SITE_KEY, {
          action,
        });
        return token;
      } catch (error) {
        console.error("Failed to execute reCAPTCHA:", error);
        return undefined;
      }
    },
    [isCaptchaEnabled, isLoaded]
  );

  return {
    getCaptchaToken,
    isCaptchaEnabled,
    isLoaded,
  };
}
