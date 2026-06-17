"use client";
import React, { useState } from "react";
import { forgotPassword } from "./utils";
import AuthFlowContainer from "@/refresh-pages/auth/AuthFlowContainer";
import { Text, Button } from "@opal/components";
import { markdown } from "@opal/utils";
import { Spacer } from "@opal/components";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { TextFormField } from "@/components/Field";
import { toast } from "@/hooks/useToast";
import { Spinner } from "@/components/Spinner";
import { redirect } from "next/navigation";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";

const ForgotPasswordPage: React.FC = () => {
  const [isWorking, setIsWorking] = useState(false);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthFlowContainer
      title="Forgot Password"
      description="Enter your email address and we'll send you a reset link."
      bottomPrompt={markdown("[Back to Login](/auth/login)")}
    >
      {isWorking && <Spinner />}
      <Formik
        initialValues={{ email: "" }}
        validationSchema={Yup.object().shape({
          email: Yup.string().email().required(),
        })}
        onSubmit={async (values) => {
          setIsWorking(true);
          try {
            await forgotPassword(values.email);
            toast.success(
              "Password reset email sent. Please check your inbox."
            );
          } catch (error) {
            const errorMessage =
              error instanceof Error
                ? error.message
                : "An error occurred. Please try again.";
            toast.error(errorMessage);
          } finally {
            setIsWorking(false);
          }
        }}
      >
        {({ isSubmitting }) => (
          <Form className="w-full flex flex-col items-stretch gap-4">
            <TextFormField
              name="email"
              label="Email"
              type="email"
              placeholder="email@yourcompany.com"
            />
            <Button disabled={isSubmitting} type="submit" width="full">
              Reset Password
            </Button>
          </Form>
        )}
      </Formik>
    </AuthFlowContainer>
  );
};

export default ForgotPasswordPage;
