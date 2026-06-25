"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { resetPassword } from "@/lib/auth/svc";
import { AuthLayouts, InputVertical } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { markdown } from "@opal/utils";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { toast } from "@/hooks/useToast";
import { useCurrentUser } from "@/hooks/useCurrentUser";

export default function ResetPasswordPage() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const { logoUrl } = useSettings();

  return (
    <AuthLayouts.Card
      title="Reset Password"
      description={`for account ${user?.email}`}
      bottomPrompt={markdown("[Back to Login](/auth/login)")}
      logoSrc={logoUrl}
    >
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
          try {
            await resetPassword(token, values.password);
            toast.success(
              "Password reset successfully. Redirecting to login..."
            );
            setTimeout(() => {
              router.replace("/auth/login");
            }, 1000);
          } catch (error) {
            toast.error(
              error instanceof Error
                ? error.message || "An error occurred during password reset."
                : "An unexpected error occurred. Please try again."
            );
          }
        }}
      >
        {({ isSubmitting }) => (
          <Form className="w-full flex flex-col items-stretch gap-4">
            <AuthLayouts.Fields>
              <InputVertical title="New Password" withLabel="password">
                <PasswordInputTypeInField
                  name="password"
                  placeholder="Enter your new password"
                />
              </InputVertical>
              <InputVertical
                title="Confirm New Password"
                withLabel="confirmPassword"
              >
                <PasswordInputTypeInField
                  name="confirmPassword"
                  placeholder="Confirm your new password"
                />
              </InputVertical>
            </AuthLayouts.Fields>
            <AuthLayouts.Submit label="reset" disabled={isSubmitting} />
          </Form>
        )}
      </Formik>
    </AuthLayouts.Card>
  );
}
