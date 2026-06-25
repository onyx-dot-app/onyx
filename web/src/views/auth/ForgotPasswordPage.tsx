"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { forgotPassword } from "@/lib/auth/svc";
import { AuthLayouts, InputVertical } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { markdown } from "@opal/utils";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { toast } from "@/hooks/useToast";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";

function ForgotPasswordPage() {
  const router = useRouter();
  const { logoUrl } = useSettings();

  useEffect(() => {
    if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
      router.replace("/auth/login");
    }
  }, [router]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) return null;

  return (
    <AuthLayouts.Card
      title="Forgot Password"
      description="Enter your email address and we'll send you a reset link."
      bottomPrompt={markdown("[Back to Login](/auth/login)")}
      logoSrc={logoUrl}
    >
      <Formik
        initialValues={{ email: "" }}
        validationSchema={Yup.object().shape({
          email: Yup.string().email().required(),
        })}
        onSubmit={async (values) => {
          try {
            await forgotPassword(values.email);
            toast.success(
              "Password reset email sent. Please check your inbox."
            );
          } catch (error) {
            toast.error(
              error instanceof Error
                ? error.message
                : "An error occurred. Please try again."
            );
          }
        }}
      >
        {({ isSubmitting }) => (
          <Form className="w-full flex flex-col items-stretch gap-4">
            <AuthLayouts.Fields>
              <InputVertical title="Email" withLabel="email">
                <InputTypeInField
                  name="email"
                  placeholder="email@yourcompany.com"
                  autoComplete="email"
                  type="email"
                />
              </InputVertical>
            </AuthLayouts.Fields>
            <AuthLayouts.Submit label="submit" disabled={isSubmitting} />
          </Form>
        )}
      </Formik>
    </AuthLayouts.Card>
  );
}

export default ForgotPasswordPage;
