"use client";

import { useEffect, useState } from "react";
import { redirect, useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import { resetPassword } from "@/lib/auth/svc";
import { AuthLayouts, InputVertical } from "@opal/layouts";
import { Formik } from "formik";
import * as Yup from "yup";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { toast } from "@/hooks/useToast";
import Cookies from "js-cookie";
import {
  NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED,
  TENANT_ID_COOKIE_NAME,
} from "@/lib/constants";
import { AUTH_SUCCESS_REDIRECT_DELAY_MS } from "@/lib/auth/constants";
import { PasswordCondition, PasswordConditions } from "@/lib/auth/components";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";
import { Logo } from "@/lib/app/components";
import { markdown } from "@opal/utils";

const initialValues = { password: "", confirmPassword: "" };

const validationSchema = Yup.object().shape({
  password: Yup.string().required("Password is required"),
  confirmPassword: Yup.string()
    .oneOf([Yup.ref("password"), undefined], "Passwords must match")
    .required("Confirm Password is required"),
});

export default function ResetPasswordPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const tenantId = searchParams?.get(TENANT_ID_COOKIE_NAME);
  const email = searchParams?.get("email");
  const [resetSuccess, setResetSuccess] = useState(false);
  const [secondsLeft, setSecondsLeft] = useState(
    AUTH_SUCCESS_REDIRECT_DELAY_MS / 1000
  );

  useEffect(() => {
    if (tenantId) {
      Cookies.set(TENANT_ID_COOKIE_NAME, tenantId, {
        path: "/",
        expires: 1 / 24,
        secure: true,
        sameSite: "lax",
      });
    }
  }, [tenantId]);

  useEffect(() => {
    if (!resetSuccess) return;
    const id = setInterval(
      () => setSecondsLeft((s) => Math.max(0, s - 1)),
      1000
    );
    const timer = setTimeout(
      () => router.replace("/auth/login" as Route),
      AUTH_SUCCESS_REDIRECT_DELAY_MS
    );
    return () => {
      clearInterval(id);
      clearTimeout(timer);
    };
  }, [resetSuccess, router]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED || !token || !email)
    redirect("/auth/login");

  async function handleSubmit(values: typeof initialValues) {
    try {
      await resetPassword(token!, values.password);
      const channel = new BroadcastChannel("password-reset");
      channel.postMessage("success");
      channel.close();
      setResetSuccess(true);
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message || "An error occurred during password reset."
          : "An unexpected error occurred. Please try again."
      );
    }
  }

  return (
    <AuthLayouts.Card
      title="Reset Password"
      description={`for account ${email}`}
      bottomPrompt={backToLoginOrSignupCopy()}
      icon={Logo}
    >
      {resetSuccess ? (
        <AuthLayouts.Message
          messageType="success"
          title="Password updated"
          description={markdown(
            `The password for the account ${email} was successfully updated.`,
            `Redirecting to login in ${secondsLeft}s or [go there now](/auth/login).`
          )}
        />
      ) : (
        <Formik
          initialValues={initialValues}
          validationSchema={validationSchema}
          onSubmit={handleSubmit}
        >
          {({ isSubmitting, isValid, dirty, values }) => (
            <AuthLayouts.FormBody>
              <AuthLayouts.Fields>
                <InputVertical title="New Password" withLabel="password">
                  <PasswordInputTypeInField
                    name="password"
                    placeholder="Choose your password"
                  />
                </InputVertical>
                <PasswordConditions password={values.password} />
                <InputVertical
                  title="Confirm Password"
                  withLabel="confirmPassword"
                >
                  <PasswordInputTypeInField
                    name="confirmPassword"
                    placeholder="Repeat your password"
                  />
                </InputVertical>
                <PasswordCondition
                  label="Passwords match"
                  met={
                    values.password.length > 0 &&
                    values.confirmPassword.length > 0 &&
                    values.password === values.confirmPassword
                  }
                />
              </AuthLayouts.Fields>
              <AuthLayouts.Submit
                label="reset"
                isSubmitting={isSubmitting}
                isValid={isValid}
                dirty={dirty}
              />
            </AuthLayouts.FormBody>
          )}
        </Formik>
      )}
    </AuthLayouts.Card>
  );
}
