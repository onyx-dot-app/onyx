"use client";

import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { useUser } from "@/components/user/UserProvider";
import { redirect, useRouter } from "next/navigation";
import { Formik, Form, FormikHelpers } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";
import { TextFormField } from "@/components/Field";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";

const ImpersonateSchema = Yup.object().shape({
  email: Yup.string().email("Invalid email").required("Required"),
  apiKey: Yup.string().required("Required"),
});

export default function ImpersonatePage() {
  const router = useRouter();
  const { user, isCloudSuperuser } = useUser();
  const { popup, setPopup } = usePopup();

  if (!user) {
    redirect("/auth/login");
  }

  if (!isCloudSuperuser) {
    redirect("/search");
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
        setPopup({
          message: errorData.detail || "Failed to impersonate user",
          type: "error",
        });
        helpers.setSubmitting(false);
      } else {
        helpers.setSubmitting(false);
        router.push("/search");
      }
    } catch (error) {
      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to impersonate user",
        type: "error",
      });
      helpers.setSubmitting(false);
    }
  };

  return (
    <AuthFlowContainer>
      {popup}
      <div className="absolute top-10x w-full">
        <HealthCheckBanner />
      </div>

      <div className="flex flex-col w-full justify-center">
        <div className="w-full flex flex-col items-center justify-center">
          <Text headingH3 className="mb-6 text-center">
            Impersonate User
          </Text>
        </div>

        <Formik
          initialValues={{ email: "", apiKey: "" }}
          validationSchema={ImpersonateSchema}
          onSubmit={(values, helpers) => handleImpersonate(values, helpers)}
        >
          {({ isSubmitting }) => (
            <Form className="flex flex-col gap-spacing-paragraph">
              <TextFormField
                name="email"
                type="email"
                label="Email"
                placeholder="email@yourcompany.com"
              />

              <TextFormField
                name="apiKey"
                type="password"
                label="API Key"
                placeholder="Enter API Key"
              />

              <Button type="submit" className="w-full" disabled={isSubmitting}>
                Impersonate User
              </Button>
            </Form>
          )}
        </Formik>

        <Text
          mainUiMuted
          text03
          className="mt-4 text-center px-4"
        >{`Note: This feature is only available for @onyx.app administrators`}</Text>
      </div>
    </AuthFlowContainer>
  );
}
