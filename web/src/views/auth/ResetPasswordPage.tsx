"use client";

import React, { useState, useEffect } from "react";
import { resetPassword } from "@/lib/auth/svc";
import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { Button } from "@opal/components";
import { markdown } from "@opal/utils";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { TextFormField } from "@/components/Field";
import { toast } from "@/hooks/useToast";
import { Spinner } from "@/components/Spinner";
import { redirect, useSearchParams } from "next/navigation";
import {
  NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED,
  TENANT_ID_COOKIE_NAME,
} from "@/lib/constants";
import Cookies from "js-cookie";

function ResetPasswordPage() {
  const [isWorking, setIsWorking] = useState(false);
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const tenantId = searchParams?.get(TENANT_ID_COOKIE_NAME);
  const { logoUrl } = useSettings();

  useEffect(() => {
    if (tenantId) {
      Cookies.set(TENANT_ID_COOKIE_NAME, tenantId, {
        path: "/",
        expires: 1 / 24,
      });
    }
  }, [tenantId]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthLayouts.Card
      title="Reset Password"
      description="Enter your new password below."
      bottomPrompt={markdown("[Back to Login](/auth/login)")}
      logoSrc={logoUrl}
    >
      {isWorking && <Spinner />}
      <Formik
        initialValues={{ password: "", confirmPassword: "" }}
        validationSchema={Yup.object().shape({
          password: Yup.string().required("Password is required"),
          confirmPassword: Yup.string()
            .oneOf([Yup.ref("password"), undefined], "Passwords must match")
            .required("Confirm Password is required"),
        })}
        onSubmit={async (values) => {
          if (!token) {
            toast.error("Invalid or missing reset token.");
            return;
          }
          setIsWorking(true);
          try {
            await resetPassword(token, values.password);
            toast.success(
              "Password reset successfully. Redirecting to login..."
            );
            setTimeout(() => {
              redirect("/auth/login");
            }, 1000);
          } catch (error) {
            if (error instanceof Error) {
              toast.error(
                error.message || "An error occurred during password reset."
              );
            } else {
              toast.error("An unexpected error occurred. Please try again.");
            }
          } finally {
            setIsWorking(false);
          }
        }}
      >
        {({ isSubmitting }) => (
          <Form className="w-full flex flex-col items-stretch gap-4">
            <TextFormField
              name="password"
              label="New Password"
              type="password"
              placeholder="Enter your new password"
            />
            <TextFormField
              name="confirmPassword"
              label="Confirm New Password"
              type="password"
              placeholder="Confirm your new password"
            />
            <Button disabled={isSubmitting} type="submit" width="full">
              Reset Password
            </Button>
          </Form>
        )}
      </Formik>
    </AuthLayouts.Card>
  );
}

export default ResetPasswordPage;
