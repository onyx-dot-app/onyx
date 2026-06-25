"use client";

import { toast } from "@/hooks/useToast";
import { basicLogin, basicSignup } from "@/lib/user";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { requestEmailVerification } from "@/lib/auth/svc";
import { useMemo, useState } from "react";
import { Spinner } from "@/components/Spinner";
import Link from "next/link";
import { useUser } from "@/providers/UserProvider";
import { validateInternalRedirect } from "@/lib/auth/redirectValidation";
import { useCaptcha } from "@/lib/hooks/useCaptcha";
import {
  AuthLayouts,
  InputVertical,
  type AuthSubmitLabel,
} from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";

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

export default function EmailPasswordForm({
  shouldVerify,
  referralSource,
  nextUrl,
  defaultEmail,
  label,
}: EmailPasswordFormProps) {
  const isSignup = label !== "submit";
  const isJoin = label === "join";

  const { user, authTypeMetadata } = useUser();
  const passwordMinLength = authTypeMetadata?.passwordMinLength ?? 8;
  const [isWorking, setIsWorking] = useState(false);
  const { getCaptchaToken } = useCaptcha();

  const initialValues: FormValues = {
    email: defaultEmail?.toLowerCase() ?? "",
    password: "",
  };

  const validationSchema = useMemo(
    () =>
      Yup.object().shape({
        email: Yup.string()
          .email()
          .required()
          .transform((value: string) => value.toLowerCase()),
        password: Yup.string()
          .min(
            passwordMinLength,
            `Password must be at least ${passwordMinLength} characters`
          )
          .required(),
      }),
    [passwordMinLength]
  );

  const handleSubmit = async (values: FormValues) => {
    const email = values.email.toLowerCase();

    if (isSignup) {
      setIsWorking(true);
      const captchaToken = await getCaptchaToken("signup");
      const response = await basicSignup(
        email,
        values.password,
        referralSource,
        captchaToken
      );

      if (!response.ok) {
        setIsWorking(false);
        const errorBody: any = await response.json();
        const errorDetail = errorBody.detail;
        let errorMsg = "Unknown error";
        if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
          errorMsg = "An account already exists with the specified email.";
        } else if (typeof errorDetail === "string" && errorDetail) {
          errorMsg = errorDetail;
        }
        if (response.status === 429) {
          errorMsg = "Too many requests. Please try again later.";
        }
        toast.error(errorMsg);
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
      if (isSignup && shouldVerify) {
        await requestEmailVerification(email);
        window.location.href = "/auth/email-verification";
      } else {
        const validatedNextUrl = validateInternalRedirect(nextUrl);
        window.location.href =
          validatedNextUrl ??
          `/app${isSignup && !isJoin ? "?new_team=true" : ""}`;
      }
    } else {
      setIsWorking(false);
      const errorDetail: any = (await loginResponse.json()).detail;
      let errorMsg = "Unknown error";
      if (errorDetail === "LOGIN_BAD_CREDENTIALS") {
        errorMsg = "Invalid email or password";
      } else if (errorDetail === "NO_WEB_LOGIN_AND_HAS_NO_PASSWORD") {
        errorMsg = "Create an account to set a password";
      } else if (typeof errorDetail === "string") {
        errorMsg = errorDetail;
      }
      if (loginResponse.status === 429) {
        errorMsg = "Too many requests. Please try again later.";
      }
      toast.error(errorMsg);
    }
  };

  return (
    <>
      {isWorking && <Spinner />}

      <Formik
        initialValues={initialValues}
        validateOnChange={true}
        validateOnBlur={true}
        validationSchema={validationSchema}
        onSubmit={handleSubmit}
      >
        {({ isSubmitting, isValid, dirty }) => {
          return (
            <Form className="flex flex-col gap-4">
              <AuthLayouts.Fields>
                <InputVertical title="Email Address" withLabel="email">
                  <InputTypeInField
                    name="email"
                    placeholder="email@yourcompany.com"
                    data-testid="email"
                    autoComplete="username"
                  />
                </InputVertical>

                <InputVertical
                  title="Password"
                  withLabel="password"
                  subDescription={
                    isSignup
                      ? `Password must be at least ${passwordMinLength} characters`
                      : undefined
                  }
                >
                  <PasswordInputTypeInField
                    name="password"
                    shrinkPlaceholder
                    data-testid="password"
                    autoComplete={
                      isSignup ? "new-password" : "current-password"
                    }
                  />
                </InputVertical>
              </AuthLayouts.Fields>

              <AuthLayouts.Submit
                label={label}
                disabled={isSubmitting || !isValid || !dirty}
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
            </Form>
          );
        }}
      </Formik>
    </>
  );
}
