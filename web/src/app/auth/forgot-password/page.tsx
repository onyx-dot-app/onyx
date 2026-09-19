"use client";
import React, { useState } from "react";
import { forgotPassword } from "./utils";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Title from "@/components/ui/title";
import { Text } from "@opal/components";
import { markdown } from "@opal/utils";
import { Spacer } from "@opal/components";
import Link from "next/link";
import { Button } from "@opal/components";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { TextFormField } from "@/components/Field";
import { toast } from "@opal/layouts";
import { Spinner } from "@/components/Spinner";
import { redirect } from "next/navigation";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import { useTranslations } from "next-intl";

const ForgotPasswordPage: React.FC = () => {
  const t = useTranslations("auth");
  const [isWorking, setIsWorking] = useState(false);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="flex">
          <Title className="mb-2 mx-auto font-bold">
            {t("forgotPassword.heading.title")}
          </Title>
        </div>
        {isWorking && <Spinner />}
        <Formik
          initialValues={{
            email: "",
          }}
          validationSchema={Yup.object().shape({
            email: Yup.string().email().required(),
          })}
          onSubmit={async (values) => {
            setIsWorking(true);
            try {
              await forgotPassword(
                values.email,
                t("forgotPassword.genericError.toast")
              );
              toast.success(t("forgotPassword.emailSent.toast"));
            } catch (error) {
              const errorMessage =
                error instanceof Error
                  ? error.message
                  : t("forgotPassword.unexpectedError.toast");
              toast.error(errorMessage);
            } finally {
              setIsWorking(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form className="w-full flex flex-col items-stretch mt-2">
              <TextFormField
                name="email"
                label={t("forgotPassword.emailField.label")}
                type="email"
                placeholder="email@yourcompany.com"
              />

              <div className="flex">
                <Button disabled={isSubmitting} type="submit" width="full">
                  {t("forgotPassword.submitButton.label")}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
        <Spacer rem={1} />
        <div className="flex">
          <div className="mx-auto">
            <Text as="p">
              {markdown(t("forgotPassword.backToLoginLink.label"))}
            </Text>
          </div>
        </div>
      </div>
    </AuthFlowContainer>
  );
};

export default ForgotPasswordPage;
