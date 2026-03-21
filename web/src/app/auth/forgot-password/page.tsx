"use client";
import React, { useState } from "react";
import { forgotPassword } from "./utils";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Title from "@/components/ui/title";
import Text from "@/components/ui/text";
import Link from "next/link";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
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
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="flex">
          <Title className="mb-2 mx-auto font-bold">
            Recuperar contrasena
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
              await forgotPassword(values.email);
              toast.success(
                "Te enviamos el correo para restablecer la contrasena."
              );
            } catch (error) {
              const errorMessage =
                error instanceof Error
                  ? error.message
                  : "Ocurrio un error. Intentalo de nuevo.";
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
                label="Correo"
                type="email"
                placeholder="correo@tuempresa.com"
              />

              <div className="flex">
                <Disabled disabled={isSubmitting}>
                  <Button type="submit" width="full">
                    Restablecer contrasena
                  </Button>
                </Disabled>
              </div>
            </Form>
          )}
        </Formik>
        <div className="flex">
          <Text className="mt-4 mx-auto">
            <Link href="/auth/login" className="text-link font-medium">
              Volver al login
            </Link>
          </Text>
        </div>
      </div>
    </AuthFlowContainer>
  );
};

export default ForgotPasswordPage;
