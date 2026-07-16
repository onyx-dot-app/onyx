"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useSessionWatcher } from "@/lib/auth/hooks";
import { getExtensionContext } from "@/lib/extension/utils";
import Modal from "@/refresh-components/Modal";
import { Button, Text } from "@opal/components";
import { SvgLogOut, SvgCheckCircle, SvgXCircle } from "@opal/icons";
import { SvgGoogle } from "@opal/logos";
import { useCaptcha } from "@/lib/hooks/useCaptcha";
import { verifyCaptchaForOAuth } from "@/lib/auth/svc";
import { basicLogin, basicSignup } from "@/lib/users/svc";
import { Formik } from "formik";
import * as Yup from "yup";
import { requestEmailVerification } from "@/lib/auth/svc";
import Link from "next/link";
import { useUser } from "@/providers/UserProvider";
import {
  validateInternalRedirect,
  passwordHasUppercase,
  passwordHasLowercase,
  passwordHasDigit,
  passwordHasSpecialChar,
  passwordMeetsLengthRequirements,
} from "@/lib/auth/utils";
import {
  AuthLayouts,
  Content,
  InputVertical,
  type AuthSubmitLabel,
  toast,
} from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { markdown } from "@opal/utils";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";

interface AuthenticationShellProps {
  children: React.ReactNode;
}

export function AuthenticationShell({ children }: AuthenticationShellProps) {
  const router = useRouter();
  const sessionEnded = useSessionWatcher();

  function handleLogin() {
    const { isExtension } = getExtensionContext();
    if (isExtension) {
      window.open(
        window.location.origin + "/auth/login",
        "_blank",
        "noopener,noreferrer"
      );
    } else {
      router.push("/auth/login");
    }
  }

  return (
    <>
      <div
        className={sessionEnded ? "pointer-events-none select-none" : undefined}
      >
        {children}
      </div>
      {sessionEnded && (
        <Modal open>
          <Modal.Content width="sm" height="sm">
            <Modal.Header icon={SvgLogOut} title="You Have Been Logged Out" />
            <Modal.Body>
              <Text font="main-ui-body" color="text-03">
                Your session has expired. Please log in again to continue.
              </Text>
            </Modal.Body>
            <Modal.Footer>
              <Button onClick={handleLogin}>Log In</Button>
            </Modal.Footer>
          </Modal.Content>
        </Modal>
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// SignInButton
//
// Renders the Google sign-in button on the login page.
//
// When reCAPTCHA is enabled for this deployment (NEXT_PUBLIC_RECAPTCHA_SITE_KEY
// set at build time), the Google OAuth click is intercepted to
// (1) fetch a reCAPTCHA v3 token for the "oauth" action, (2) POST it to
// /api/auth/captcha/oauth-verify which sets a signed HttpOnly cookie on the
// response, and (3) then navigate to the authorize URL. The cookie is sent
// automatically on the subsequent Google redirect back to our callback,
// where the backend middleware verifies it.
//
// IMPORTANT: This component is rendered as part of the /auth/login page, which
// is used in healthcheck and monitoring flows that issue headless (non-browser)
// requests (e.g. `curl`). During server-side rendering of those requests,
// browser-only globals like `window`, `document`, `navigator`, etc. are NOT
// available. Even though this file is marked "use client", Next.js still
// executes the component body on the server during SSR — only hooks like
// `useEffect` are skipped.
//
// Do NOT reference `window` or other browser APIs in the render path of this
// component. If you need browser globals, gate them behind `useEffect` or
// `typeof window !== "undefined"` checks inside callbacks/effects — but be
// aware that Turbopack may optimise away bare `typeof window` guards in the
// SSR bundle, so prefer `useEffect` for safety.
// ---------------------------------------------------------------------------

interface SignInButtonProps {
  authorizeUrl: string;
}

export function SignInButton({ authorizeUrl }: SignInButtonProps) {
  const { getCaptchaToken, isCaptchaEnabled } = useCaptcha();
  const [isVerifying, setIsVerifying] = useState(false);

  async function handleClick(e: React.MouseEvent) {
    e.preventDefault();
    if (isVerifying) return;
    setIsVerifying(true);
    // Stays true on the success branch so the button remains disabled until
    // the browser actually begins unloading for the OAuth redirect — prevents
    // a double-click window between `window.location.href = ...` and unload.
    let navigating = false;
    try {
      const token = await getCaptchaToken("oauth");
      if (!token) {
        toast.error("grecaptcha.execute returned no token");
        return;
      }
      await verifyCaptchaForOAuth(token);
      navigating = true;
      window.location.href = authorizeUrl;
    } catch (exc) {
      toast.error(exc instanceof Error ? exc.message : String(exc));
    } finally {
      if (!navigating) setIsVerifying(false);
    }
  }

  // The Google OAuth callback is gated by CaptchaCookieMiddleware on the
  // backend, so the click is intercepted whenever reCAPTCHA is enabled.
  const intercepted = isCaptchaEnabled;

  return (
    <Button
      prominence="secondary"
      width="full"
      icon={SvgGoogle}
      href={intercepted ? undefined : authorizeUrl}
      onClick={intercepted ? handleClick : undefined}
      disabled={isVerifying}
    >
      Continue with Google
    </Button>
  );
}

// ---------------------------------------------------------------------------
// PasswordRequirements
// ---------------------------------------------------------------------------

interface PasswordRequirementsProps {
  password: string;
}

export function PasswordRequirements({ password }: PasswordRequirementsProps) {
  const { authTypeMetadata } = useUser();

  if (!authTypeMetadata) return null;

  const {
    passwordMinLength,
    passwordMaxLength,
    passwordRequireUppercase,
    passwordRequireLowercase,
    passwordRequireDigit,
    passwordRequireSpecialChar,
  } = authTypeMetadata;

  const rules = (
    [
      {
        label: `${passwordMinLength}–${passwordMaxLength} characters`,
        met: passwordMeetsLengthRequirements(
          password,
          passwordMinLength,
          passwordMaxLength
        ),
      },
      passwordRequireUppercase && {
        label: "Contains uppercase letter.",
        met: passwordHasUppercase(password),
      },
      passwordRequireLowercase && {
        label: "Contains lowercase letter.",
        met: passwordHasLowercase(password),
      },
      passwordRequireDigit && {
        label: "Contains number.",
        met: passwordHasDigit(password),
      },
      passwordRequireSpecialChar && {
        label: "Contains special character.",
        met: passwordHasSpecialChar(password),
      },
    ] as const
  ).filter((r): r is { label: string; met: boolean } => Boolean(r));

  return (
    <div className="flex flex-col gap-1">
      {rules.map((rule) => (
        <Content
          key={rule.label}
          sizePreset="secondary"
          variant="body"
          icon={rule.met ? SvgCheckCircle : SvgXCircle}
          color={rule.met ? "success" : "muted"}
          title={rule.label}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// EmailPasswordForm
// ---------------------------------------------------------------------------

interface FormValues {
  email: string;
  password: string;
}

export interface EmailPasswordFormProps {
  shouldVerify?: boolean;
  referralSource?: string;
  nextUrl?: string | null;
  defaultEmail?: string | null;
  label: AuthSubmitLabel;
}

export function EmailPasswordForm({
  shouldVerify,
  referralSource,
  nextUrl,
  defaultEmail,
  label,
}: EmailPasswordFormProps) {
  const isSignup = label !== "submit";
  const isJoin = label === "join";

  const { user, authTypeMetadata } = useUser();
  const { getCaptchaToken } = useCaptcha();

  const validationSchema = useMemo(() => {
    let passwordSchema = Yup.string();

    if (isSignup) {
      const minLength = authTypeMetadata?.passwordMinLength ?? 0;
      const maxLength = authTypeMetadata?.passwordMaxLength ?? Infinity;

      passwordSchema = passwordSchema.test(
        "length",
        `Password must be between ${minLength}–${maxLength} characters`,
        (v) => passwordMeetsLengthRequirements(v ?? "", minLength, maxLength)
      );

      if (authTypeMetadata?.passwordRequireUppercase)
        passwordSchema = passwordSchema.test(
          "uppercase",
          "Password must contain at least one uppercase letter",
          (v) => passwordHasUppercase(v ?? "")
        );
      if (authTypeMetadata?.passwordRequireLowercase)
        passwordSchema = passwordSchema.test(
          "lowercase",
          "Password must contain at least one lowercase letter",
          (v) => passwordHasLowercase(v ?? "")
        );
      if (authTypeMetadata?.passwordRequireDigit)
        passwordSchema = passwordSchema.test(
          "digit",
          "Password must contain at least one number",
          (v) => passwordHasDigit(v ?? "")
        );
      if (authTypeMetadata?.passwordRequireSpecialChar)
        passwordSchema = passwordSchema.test(
          "special-char",
          "Password must contain at least one special character",
          (v) => passwordHasSpecialChar(v ?? "")
        );
    }

    return Yup.object().shape({
      email: Yup.string()
        .email()
        .required()
        .transform((value: string) => value.toLowerCase()),
      password: passwordSchema.required(),
    });
  }, [isSignup, authTypeMetadata]);

  const initialValues: FormValues = {
    email: defaultEmail?.toLowerCase() ?? "",
    password: "",
  };

  async function handleSubmit(values: FormValues) {
    const email = values.email.toLowerCase();

    if (isSignup) {
      const captchaToken = await getCaptchaToken("signup");
      const response = await basicSignup(
        email,
        values.password,
        referralSource,
        captchaToken
      );

      if (!response.ok) {
        const errorBody: any = await response.json().catch(() => ({}));
        const errorDetail = errorBody.detail;
        let errorMsg = "Unknown error";
        if (response.status === 429) {
          errorMsg = "Too many requests. Please try again later.";
        } else if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
          errorMsg = "An account already exists with the specified email.";
        } else if (typeof errorDetail === "string" && errorDetail) {
          errorMsg = errorDetail;
        }
        toast.error(errorMsg);
        return;
      }

      // On verification-required deployments the server blocks login until the
      // email is confirmed, so we must NOT call basicLogin first — it would
      // fail and leave the user stranded even though the account was created.
      if (shouldVerify) {
        try {
          await requestEmailVerification(email);
        } catch (e) {
          // Best-effort: the account already exists, so redirect regardless.
          console.warn("requestEmailVerification failed:", e);
        }
        window.location.href = "/auth/waiting-on-verification";
        return;
      }
    }

    const loginCaptchaToken = await getCaptchaToken("login");
    const loginResponse = await basicLogin(
      email,
      values.password,
      loginCaptchaToken
    );

    if (loginResponse.ok) {
      const validatedNextUrl = validateInternalRedirect(nextUrl);
      window.location.href =
        validatedNextUrl ??
        `/app${isSignup && !isJoin ? "?new_team=true" : ""}`;
    } else {
      const errorBody: any = await loginResponse.json().catch(() => ({}));
      const errorDetail = errorBody.detail;
      let errorMsg = "Unknown error";
      if (loginResponse.status === 429) {
        errorMsg = "Too many requests. Please try again later.";
      } else if (errorDetail === "LOGIN_BAD_CREDENTIALS") {
        errorMsg = "Invalid email or password";
      } else if (errorDetail === "NO_WEB_LOGIN_AND_HAS_NO_PASSWORD") {
        errorMsg = "Create an account to set a password";
      } else if (typeof errorDetail === "string") {
        errorMsg = errorDetail;
      }
      toast.error(errorMsg);
    }
  }

  return (
    <Formik
      initialValues={initialValues}
      enableReinitialize
      validateOnChange={true}
      validateOnBlur={true}
      validationSchema={validationSchema}
      onSubmit={handleSubmit}
    >
      {({ isSubmitting, isValid, dirty, values, errors }) => {
        return (
          <AuthLayouts.FormBody>
            <AuthLayouts.Fields>
              <InputVertical title="Email Address" withLabel="email">
                <InputTypeInField
                  name="email"
                  placeholder="email@yourcompany.com"
                  data-testid="email"
                  autoComplete="username"
                />
              </InputVertical>

              <div className="flex flex-col gap-1">
                <InputVertical
                  title="Password"
                  withLabel="password"
                  topRight={
                    NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED &&
                    !isSignup &&
                    !errors.email &&
                    !!values.email
                      ? markdown(
                          `[Forgot password?](/auth/forgot-password?email=${encodeURIComponent(values.email)})`
                        )
                      : undefined
                  }
                  subDescription={
                    isSignup ? "Password requirements:" : undefined
                  }
                >
                  <PasswordInputTypeInField
                    name="password"
                    placeholder="Password"
                    data-testid="password"
                    autoComplete={
                      isSignup ? "new-password" : "current-password"
                    }
                  />
                </InputVertical>
                {isSignup && (
                  <PasswordRequirements password={values.password} />
                )}
              </div>
            </AuthLayouts.Fields>

            <AuthLayouts.Submit
              label={label}
              isSubmitting={isSubmitting}
              isValid={isValid && (!isSignup || Boolean(authTypeMetadata))}
              dirty={dirty}
            />

            {user?.is_anonymous_user && (
              <Link
                href="/app"
                className="text-xs text-action-link-05 cursor-pointer text-center w-full font-medium mx-auto"
              >
                <span className="hover:border-b hover:border-dotted hover:border-action-link-05">
                  or continue as guest
                </span>
              </Link>
            )}
          </AuthLayouts.FormBody>
        );
      }}
    </Formik>
  );
}
