"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";

import { useUser } from "@/providers/UserProvider";
import { redirect, useRouter } from "next/navigation";
import type { Route } from "next";
import { Formik, Form, FormikHelpers } from "formik";
import * as Yup from "yup";
import { toast } from "@/hooks/useToast";
import { TextFormField } from "@/components/Field";
import { Button } from "@opal/components";
import { Disabled } from "@opal/core";
import Text from "@/refresh-components/texts/Text";

const ImpersonateSchema = Yup.object().shape({
  email: Yup.string()
    .email("Correo electrónico inválido")
    .required("Campo obligatorio"),
  apiKey: Yup.string().required("Campo obligatorio"),
});

export default function ImpersonatePage() {
  const router = useRouter();
  const { user, isCloudSuperuser } = useUser();
  if (!user) {
    redirect("/auth/login");
  }

  if (!isCloudSuperuser) {
    redirect("/app" as Route);
  }

  const handleImpersonate = async (
    values: { email: string; apiKey: string },
    helpers: FormikHelpers<{ email: string; apiKey: string }>
  ) => {
    try {
      const response = await fetch("/api/tenants/impersonate", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${values.apiKey}`,
        },
        body: JSON.stringify({ email: values.email }),
        credentials: "same-origin",
      });

      if (!response.ok) {
        const errorData = await response.json();
        toast.error(errorData.detail || "No se pudo suplantar al usuario");
        helpers.setSubmitting(false);
      } else {
        helpers.setSubmitting(false);
        router.push("/app" as Route);
      }
    } catch (error) {
      toast.error(
        error instanceof Error
          ? error.message
          : "No se pudo suplantar al usuario"
      );
      helpers.setSubmitting(false);
    }
  };

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="w-full flex flex-col items-center justify-center">
          <Text as="p" headingH3 className="mb-6 text-center">
            Suplantar usuario
          </Text>
        </div>

        <Formik
          initialValues={{ email: "", apiKey: "" }}
          validationSchema={ImpersonateSchema}
          onSubmit={(values, helpers) => handleImpersonate(values, helpers)}
        >
          {({ isSubmitting }) => (
            <Form className="flex flex-col gap-4">
              <TextFormField
                name="email"
                type="email"
                label="Correo electrónico"
                placeholder="correo@tuempresa.com"
              />

              <TextFormField
                name="apiKey"
                type="password"
                label="Clave de API"
                placeholder="Ingresa la clave de API"
              />

              <Disabled disabled={isSubmitting}>
                <Button type="submit" width="full">
                  Suplantar usuario
                </Button>
              </Disabled>
            </Form>
          )}
        </Formik>

        <Text
          as="p"
          mainUiMuted
          text03
          className="mt-4 text-center px-4"
        >
          Esta función solo está disponible para administradores internos.
        </Text>
      </div>
    </AuthFlowContainer>
  );
}
