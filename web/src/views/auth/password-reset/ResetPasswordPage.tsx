"use client";

import { useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { redirect } from "next/navigation";
import { resetPassword } from "@/lib/auth/svc";
import { AuthLayouts, InputVertical } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { Formik } from "formik";
import * as Yup from "yup";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { toast } from "@/hooks/useToast";
import Cookies from "js-cookie";
import {
  NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED,
  TENANT_ID_COOKIE_NAME,
} from "@/lib/constants";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";
import type { Route } from "next";

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
  const { logoUrl } = useSettings();

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

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) redirect("/auth/login");
  if (!token) redirect("/auth/forgot-password" as Route);
  if (!email) redirect("/auth/login" as Route);

  async function handleSubmit(values: typeof initialValues) {
    try {
      await resetPassword(token!, values.password);
      toast.success("Password reset successfully. Redirecting to login...");
      setTimeout(() => {
        router.replace("/auth/login" as Route);
      }, 1000);
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
      logoSrc={logoUrl}
    >
      <Formik
        initialValues={initialValues}
        validationSchema={validationSchema}
        onSubmit={handleSubmit}
      >
        {({ isSubmitting, isValid, dirty }) => (
          <AuthLayouts.FormBody>
            <AuthLayouts.Fields>
              <InputVertical title="New Password" withLabel="password">
                <PasswordInputTypeInField
                  name="password"
                  placeholder="Choose your password"
                />
              </InputVertical>
              <InputVertical
                title="Confirm Password"
                withLabel="confirmPassword"
              >
                <PasswordInputTypeInField
                  name="confirmPassword"
                  placeholder="Repeat your password"
                />
              </InputVertical>
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
    </AuthLayouts.Card>
  );
}
