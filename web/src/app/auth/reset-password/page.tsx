"use client";
import React, { useState, useEffect } from "react";
import { resetPassword } from "../forgot-password/utils";
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
import { redirect, useSearchParams } from "next/navigation";
import {
  LEGACY_RESET_PASSWORD_TENANT_QUERY_PARAM,
  LEGACY_TENANT_ID_COOKIE_NAME,
  NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED,
  TENANT_ID_COOKIE_NAME,
} from "@/lib/constants";
import Cookies from "js-cookie";

const ResetPasswordPage: React.FC = () => {
  const [isWorking, setIsWorking] = useState(false);
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const tenantId =
    searchParams?.get(TENANT_ID_COOKIE_NAME) ??
    searchParams?.get(LEGACY_TENANT_ID_COOKIE_NAME) ??
    searchParams?.get(LEGACY_RESET_PASSWORD_TENANT_QUERY_PARAM);

  useEffect(() => {
    if (tenantId) {
      Cookies.set(TENANT_ID_COOKIE_NAME, tenantId, {
        path: "/",
        expires: 1 / 24,
      }); // Expires in 1 hour
      Cookies.remove(LEGACY_TENANT_ID_COOKIE_NAME, { path: "/" });
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
            Restablecer contrasena
          </Title>
        </div>
        {isWorking && <Spinner />}
        <Formik
          initialValues={{
            password: "",
            confirmPassword: "",
          }}
          validationSchema={Yup.object().shape({
            password: Yup.string().required("La contrasena es obligatoria"),
            confirmPassword: Yup.string()
              .oneOf([Yup.ref("password"), undefined], "Las contrasenas no coinciden")
              .required("Confirma tu contrasena"),
          })}
          onSubmit={async (values) => {
            if (!token) {
              toast.error("El token para restablecer no es valido.");
              return;
            }
            setIsWorking(true);
            try {
              await resetPassword(token, values.password);
              toast.success(
                "Contrasena actualizada. Redirigiendo al login..."
              );
              setTimeout(() => {
                redirect("/auth/login");
              }, 1000);
            } catch (error) {
              if (error instanceof Error) {
                toast.error(
                  error.message ||
                    "Ocurrio un error mientras actualizabamos tu contrasena."
                );
              } else {
                toast.error("Ocurrio un error inesperado. Intentalo de nuevo.");
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
                label="Nueva contrasena"
                type="password"
                placeholder="Ingresa tu nueva contrasena"
              />
              <TextFormField
                name="confirmPassword"
                label="Confirma la contrasena"
                type="password"
                placeholder="Confirma tu nueva contrasena"
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

export default ResetPasswordPage;
