"use client";
import React, { useState } from "react";
import { resetPassword } from "../forgot-password/utils";
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
import { redirect, useSearchParams } from "next/navigation";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import { useTranslations } from "next-intl";

const ResetPasswordPage: React.FC = () => {
  const t = useTranslations("auth");
  const [isWorking, setIsWorking] = useState(false);
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  const genericError = t("resetPassword.genericError.toast");

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="flex">
          <Title className="mb-2 mx-auto font-bold">
            {t("resetPassword.heading.title")}
          </Title>
        </div>
        {isWorking && <Spinner />}
        <Formik
          initialValues={{
            password: "",
            confirmPassword: "",
          }}
          validationSchema={Yup.object().shape({
            password: Yup.string().required(
              t("resetPassword.passwordRequired.error")
            ),
            confirmPassword: Yup.string()
              .oneOf(
                [Yup.ref("password"), undefined],
                t("resetPassword.passwordsMatch.error")
              )
              .required(t("resetPassword.confirmPasswordRequired.error")),
          })}
          onSubmit={async (values) => {
            if (!token) {
              toast.error(t("resetPassword.missingToken.toast"));
              return;
            }
            setIsWorking(true);
            try {
              await resetPassword(token, values.password, {
                invalidPassword: t("resetPassword.invalidPassword.error"),
                genericError,
              });
              toast.success(t("resetPassword.successRedirect.toast"));
              setTimeout(() => {
                redirect("/auth/login");
              }, 1000);
            } catch (error) {
              if (error instanceof Error) {
                toast.error(error.message || genericError);
              } else {
                toast.error(t("resetPassword.unexpectedError.toast"));
              }
            } finally {
              setIsWorking(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form className="w-full flex flex-col items-stretch mt-2">
              <TextFormField
                name="password"
                label={t("resetPassword.newPasswordField.label")}
                type="password"
                placeholder={t("resetPassword.newPasswordField.placeholder")}
              />
              <TextFormField
                name="confirmPassword"
                label={t("resetPassword.confirmPasswordField.label")}
                type="password"
                placeholder={t(
                  "resetPassword.confirmPasswordField.placeholder"
                )}
              />

              <div className="flex">
                <Button disabled={isSubmitting} type="submit" width="full">
                  {t("resetPassword.submitButton.label")}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
        <Spacer rem={1} />
        <div className="flex">
          <div className="mx-auto">
            <Text as="p">
              {markdown(t("resetPassword.backToLoginLink.label"))}
            </Text>
          </div>
        </div>
      </div>
    </AuthFlowContainer>
  );
};

export default ResetPasswordPage;
