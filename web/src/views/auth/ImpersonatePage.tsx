"use client";

import { AuthLayouts } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { useUser } from "@/providers/UserProvider";
import { redirect, useRouter } from "next/navigation";
import type { Route } from "next";
import { Formik, Form, FormikHelpers } from "formik";
import * as Yup from "yup";
import { toast } from "@/hooks/useToast";
import { TextFormField } from "@/components/Field";
import { Button, Text } from "@opal/components";

const ImpersonateSchema = Yup.object().shape({
  email: Yup.string().email("Invalid email").required("Required"),
  apiKey: Yup.string().required("Required"),
});

export default function ImpersonatePage() {
  const router = useRouter();
  const { user, isCloudSuperuser } = useUser();
  const { logoUrl } = useSettings();

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
        toast.error(errorData.detail || "Failed to impersonate user");
        helpers.setSubmitting(false);
      } else {
        helpers.setSubmitting(false);
        router.push("/app" as Route);
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to impersonate user"
      );
      helpers.setSubmitting(false);
    }
  };

  return (
    <AuthLayouts.Card
      title="Impersonate User"
      description="Cloud superuser access only."
      logoSrc={logoUrl}
    >
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
              label="Email"
              placeholder="email@yourcompany.com"
            />
            <TextFormField
              name="apiKey"
              type="password"
              label="API Key"
              placeholder="Enter API Key"
            />
            <Button disabled={isSubmitting} type="submit" width="full">
              Impersonate
            </Button>
          </Form>
        )}
      </Formik>
      <div className="mt-4 text-center px-4">
        <Text as="p" font="main-ui-body" color="text-03">
          Note: This feature is only available for @onyx.app administrators
        </Text>
      </div>
    </AuthLayouts.Card>
  );
}
