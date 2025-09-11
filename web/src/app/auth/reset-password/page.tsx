"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";
import React, { useState, useEffect } from "react";
import { resetPassword } from "../forgot-password/utils";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import CardSection from "@/components/admin/CardSection";
import Title from "@/components/ui/title";
import Text from "@/components/ui/text";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { TextFormField } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Spinner } from "@/components/Spinner";
import { redirect, useSearchParams } from "next/navigation";
import {
  NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED,
  TENANT_ID_COOKIE_NAME,
} from "@/lib/constants";
import Cookies from "js-cookie";

const ResetPasswordPage: React.FC = () => {
  const { popup, setPopup } = usePopup();
  const [isWorking, setIsWorking] = useState(false);
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const tenantId = searchParams?.get(TENANT_ID_COOKIE_NAME);
  // Keep search param same name as cookie for simplicity

  useEffect(() => {
    if (tenantId) {
      Cookies.set(TENANT_ID_COOKIE_NAME, tenantId, {
        path: "/",
        expires: 1 / 24,
      }); // Expires in 1 hour
    }
  }, [tenantId]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="flex">
          <Title className="mb-2 mx-auto font-bold">
            {i18n.t(k.RESET_PASSWORD)}
          </Title>
        </div>
        {isWorking && <Spinner />}
        {popup}
        <Formik
          initialValues={{
            password: "",
            confirmPassword: "",
          }}
          validationSchema={Yup.object().shape({
            password: Yup.string().required(i18n.t(k.PASSWORD_REQUIRED)),
            confirmPassword: Yup.string()
              .oneOf(
                [Yup.ref("password"), undefined],
                i18n.t(k.PASSWORDS_MUST_MATCH)
              )
              .required(i18n.t(k.CONFIRM_PASSWORD_REQUIRED)),
          })}
          onSubmit={async (values) => {
            if (!token) {
              setPopup({
                type: "error",
                message: i18n.t(k.INVALID_OR_MISSING_RESET_TOKEN),
              });
              return;
            }
            setIsWorking(true);
            try {
              await resetPassword(token, values.password);
              setPopup({
                type: "success",
                message: i18n.t(k.PASSWORD_RESET_SUCCESSFULLY_R),
              });
              setTimeout(() => {
                redirect("/auth/login");
              }, 1000);
            } catch (error) {
              if (error instanceof Error) {
                setPopup({
                  type: "error",
                  message: error.message || i18n.t(k.PASSWORD_RESET_ERROR),
                });
              } else {
                setPopup({
                  type: "error",
                  message: i18n.t(k.AN_UNEXPECTED_ERROR_OCCURRED),
                });
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
                label={i18n.t(k.NEW_PASSWORD)}
                type="password"
                placeholder={i18n.t(k.ENTER_NEW_PASSWORD)}
              />

              <TextFormField
                name="confirmPassword"
                label={i18n.t(k.CONFIRM_NEW_PASSWORD)}
                type="password"
                placeholder={i18n.t(k.CONFIRM_NEW_PASSWORD_PLACEHOLDER)}
              />

              <div className="flex">
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="mx-auto w-full"
                >
                  {i18n.t(k.RESET_PASSWORD)}
                </Button>
              </div>
            </Form>
          )}
        </Formik>
        <div className="flex">
          <Text className="mt-4 mx-auto">
            <Link href="/auth/login" className="text-link font-medium">
              {i18n.t(k.BACK_TO_LOGIN)}
            </Link>
          </Text>
        </div>
      </div>
    </AuthFlowContainer>
  );
};

export default ResetPasswordPage;
