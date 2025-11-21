"use client";
import React, { useState } from "react";
import { forgotPassword } from "./utils";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Title from "@/components/ui/title";
import Text from "@/components/ui/text";
import Link from "next/link";
import Button from "@/refresh-components/buttons/Button";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { TextFormField } from "@/components/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { Spinner } from "@/components/Spinner";
import { redirect } from "next/navigation";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";

const ForgotPasswordPage: React.FC = () => {
  const { popup, setPopup } = usePopup();
  const [isWorking, setIsWorking] = useState(false);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="flex">
          <Title className="mb-2 mx-auto font-bold">Mot de passe oublié</Title>
        </div>
        {isWorking && <Spinner />}
        {popup}
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
              await forgotPassword(values.email);
              setPopup({
                type: "success",
                message: "Email de réinitialisation de mot de passe envoyé. Veuillez vérifier votre boîte de réception.",
              });
            } catch (error) {
              const errorMessage =
                error instanceof Error
                  ? error.message
                  : "Une erreur est survenue. Veuillez réessayer.";
              setPopup({
                type: "error",
                message: errorMessage,
              });
            } finally {
              setIsWorking(false);
            }
          }}
        >
          {({ isSubmitting }) => (
            <Form className="w-full flex flex-col items-stretch mt-2">
              <TextFormField
                name="email"
                label="Email"
                type="email"
                placeholder="email@votredomaine.com"
              />

              <div className="flex">
                <Button
                  type="submit"
                  disabled={isSubmitting}
                  className="mx-auto w-full"
                >
                  Réinitialiser le mot de passe
                </Button>
              </div>
            </Form>
          )}
        </Formik>
        <div className="flex">
          <Text className="mt-4 mx-auto">
            <Link href="/auth/login" className="text-link font-medium">
              Retour à la connexion
            </Link>
          </Text>
        </div>
      </div>
    </AuthFlowContainer>
  );
};

export default ForgotPasswordPage;
