"use client";

import { usePopup } from "@/components/admin/connectors/Popup";
import { basicLogin, basicSignup } from "@/lib/user";
import Button from "@/refresh-components/buttons/Button";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { requestEmailVerification } from "../lib";
import { useMemo, useState } from "react";
import { Spinner } from "@/components/Spinner";
import Link from "next/link";
import { useUser } from "@/components/user/UserProvider";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import { validateInternalRedirect } from "@/lib/auth/redirectValidation";
import { APIFormFieldState } from "@/refresh-components/form/types";
import { SvgArrowRightCircle } from "@opal/icons";
import { useCaptcha } from "@/lib/hooks/useCaptcha";

interface EmailPasswordFormProps {
  isSignup?: boolean;
  shouldVerify?: boolean;
  referralSource?: string;
  nextUrl?: string | null;
  defaultEmail?: string | null;
  isJoin?: boolean;
}

export default function EmailPasswordForm({
  isSignup = false,
  shouldVerify,
  referralSource,
  nextUrl,
  defaultEmail,
  isJoin = false,
}: EmailPasswordFormProps) {
  const { user, authTypeMetadata } = useUser();
  const passwordMinLength = authTypeMetadata?.passwordMinLength ?? 8;
  const { popup, setPopup } = usePopup();
  const [isWorking, setIsWorking] = useState<boolean>(false);
  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const { getCaptchaToken } = useCaptcha();

  const apiMessages = useMemo(
    () => ({
      loading: isSignup
        ? isJoin
          ? "Joining..."
          : "Creating account..."
        : "Signing in...",
      success: isSignup
        ? "Account created. Signing in..."
        : "Signed in successfully.",
      error: errorMessage,
    }),
    [isSignup, isJoin, errorMessage]
  );

  return (
    <>
      {isWorking && <Spinner />}
      {popup}

      <Formik
        initialValues={{
          email: defaultEmail ? defaultEmail.toLowerCase() : "",
          password: "",
        }}
        validateOnChange={true}
        validateOnBlur={true}
        validationSchema={Yup.object().shape({
          email: Yup.string()
            .email()
            .required()
            .transform((value) => value.toLowerCase()),
          password: Yup.string()
            .min(
              passwordMinLength,
              `Password must be at least ${passwordMinLength} characters`
            )
            .required(),
        })}
        onSubmit={async (values: { email: string; password: string }) => {
          // Ensure email is lowercase
          const email: string = values.email.toLowerCase();
          setShowApiMessage(true);
          setApiStatus("loading");
          setErrorMessage("");

          if (isSignup) {
            // login is fast, no need to show a spinner
            setIsWorking(true);

            // Get captcha token for signup (if captcha is enabled)
            const captchaToken = await getCaptchaToken("signup");

            const response = await basicSignup(
              email,
              values.password,
              referralSource,
              captchaToken
            );

            if (!response.ok) {
              setIsWorking(false);

              const errorDetail: any = (await response.json()).detail;
              let errorMsg: string = "Unknown error";
              if (typeof errorDetail === "object" && errorDetail.reason) {
                errorMsg = errorDetail.reason;
              } else if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
                errorMsg =
                  "An account already exists with the specified email.";
              }
              if (response.status === 429) {
                errorMsg = "Too many requests. Please try again later.";
              }
              setErrorMessage(errorMsg);
              setApiStatus("error");
              setPopup({
                type: "error",
                message: `Failed to sign up - ${errorMsg}`,
              });
              setIsWorking(false);
              return;
            } else {
              setApiStatus("success");
              setPopup({
                type: "success",
                message: "Account created successfully. Please log in.",
              });
            }
          }

          const loginResponse = await basicLogin(email, values.password);
          if (loginResponse.ok) {
            setApiStatus("success");
            if (isSignup && shouldVerify) {
              await requestEmailVerification(email);
              // Use window.location.href to force a full page reload,
              // ensuring app re-initializes with the new state (including
              // server-side provider values)
              window.location.href = "/auth/waiting-on-verification";
            } else {
              // The searchparam is purely for multi tenant developement purposes.
              // It replicates the behavior of the case where a user
              // has signed up with email / password as the only user to an instance
              // and has just completed verification
              const validatedNextUrl = validateInternalRedirect(nextUrl);
              window.location.href = validatedNextUrl
                ? validatedNextUrl
                : `/chat${isSignup && !isJoin ? "?new_team=true" : ""}`;
            }
          } else {
            setIsWorking(false);
            const errorDetail: any = (await loginResponse.json()).detail;
            let errorMsg: string = "Unknown error";
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
            setErrorMessage(errorMsg);
            setApiStatus("error");
            setPopup({
              type: "error",
              message: `Failed to login - ${errorMsg}`,
            });
          }
        }}
      >
        {({ isSubmitting, isValid, dirty, values }) => {
          return (
            <Form className="gap-y-3">
              <FormikField<string>
                name="email"
                render={(field, helper, meta, state) => (
                  <FormField name="email" state={state} className="w-full">
                    <FormField.Label>Email Address</FormField.Label>
                    <FormField.Control>
                      <InputTypeIn
                        {...field}
                        onChange={(e) => {
                          if (showApiMessage && apiStatus === "error") {
                            setShowApiMessage(false);
                            setErrorMessage("");
                            setApiStatus("loading");
                          }
                          field.onChange(e);
                        }}
                        placeholder="email@yourcompany.com"
                        onClear={() => helper.setValue("")}
                        data-testid="email"
                        error={apiStatus === "error"}
                        showClearButton={false}
                      />
                    </FormField.Control>
                  </FormField>
                )}
              />

              <FormikField<string>
                name="password"
                render={(field, helper, meta, state) => (
                  <FormField name="password" state={state} className="w-full">
                    <FormField.Label>Password</FormField.Label>
                    <FormField.Control>
                      <PasswordInputTypeIn
                        {...field}
                        onChange={(e) => {
                          if (showApiMessage && apiStatus === "error") {
                            setShowApiMessage(false);
                            setErrorMessage("");
                            setApiStatus("loading");
                          }
                          field.onChange(e);
                        }}
                        placeholder="**************"
                        onClear={() => helper.setValue("")}
                        data-testid="password"
                        error={apiStatus === "error"}
                        showClearButton={false}
                      />
                    </FormField.Control>
                    {isSignup && !showApiMessage && (
                      <FormField.Message
                        messages={{
                          idle: `Password must be at least ${passwordMinLength} characters`,
                          error: meta.error,
                          success: `Password must be at least ${passwordMinLength} characters`,
                        }}
                      />
                    )}
                    {showApiMessage && (
                      <FormField.APIMessage
                        state={apiStatus}
                        messages={apiMessages}
                      />
                    )}
                  </FormField>
                )}
              />

              <Button
                type="submit"
                className="w-full mt-1"
                disabled={isSubmitting || !isValid || !dirty}
                rightIcon={SvgArrowRightCircle}
              >
                {isJoin ? "Join" : isSignup ? "Create Account" : "Sign In"}
              </Button>
              {user?.is_anonymous_user && (
                <Link
                  href="/chat"
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
