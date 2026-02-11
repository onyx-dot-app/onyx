/**
 * Type declarations for Google reCAPTCHA.
 * Used by both v2 and v3 captcha hooks.
 */

declare global {
  interface Window {
    grecaptcha?: {
      // v3 methods
      ready: (callback: () => void) => void;
      execute: (
        siteKey: string,
        options: { action: string }
      ) => Promise<string>;
      // v2 methods
      render: (
        container: string | HTMLElement,
        options: {
          sitekey: string;
          callback: (response: string) => void;
          "expired-callback"?: () => void;
          "error-callback"?: () => void;
        }
      ) => number;
      reset: (widgetId: number) => void;
    };
    // v2 onload callback
    onRecaptchaV2Load?: () => void;
  }
}

export {};
