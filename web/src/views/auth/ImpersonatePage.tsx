"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { AuthLayouts, InputVertical } from "@opal/layouts";
import { useSettings } from "@/lib/settings/hooks";
import { useCurrentUser } from "@/lib/users/hooks";
import { Formik, Form, type FormikHelpers } from "formik";
import * as Yup from "yup";
import { toast } from "@/hooks/useToast";
import { impersonateUser } from "@/lib/auth/svc";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";
import { markdown } from "@opal/utils";
import { backToLoginOrSignupCopy } from "@/lib/auth/copies";
import { getAppLogo } from "@/lib/app/utils";

const initialValues = { email: "", apiKey: "" };

const impersonationSchema = Yup.object().shape({
  email: Yup.string().email("Invalid email").required("Required"),
  apiKey: Yup.string().required("Required"),
});

export default function ImpersonatePage() {
  const router = useRouter();
  const { user } = useCurrentUser();
  const { logoUrl } = useSettings();

  useEffect(() => {
    if (user === undefined) return;

    if (!user || !user.is_active || user.is_anonymous_user) {
      router.replace("/auth/login" as Route);
      return;
    }

    if (!user.is_cloud_superuser) {
      router.replace("/app" as Route);
    }
  }, [user, router]);

  async function handleImpersonate(
    values: { email: string; apiKey: string },
    helpers: FormikHelpers<{ email: string; apiKey: string }>
  ) {
    try {
      await impersonateUser(values.email, values.apiKey);
      router.push("/app" as Route);
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "Failed to impersonate user"
      );
    } finally {
      helpers.setSubmitting(false);
    }
  }

  return (
    <AuthLayouts.Card
      title="Impersonate User"
      description="Cloud superuser access only."
      bottomPrompt={backToLoginOrSignupCopy()}
      icon={getAppLogo(logoUrl)}
    >
      <Formik
        initialValues={initialValues}
        validationSchema={impersonationSchema}
        onSubmit={handleImpersonate}
      >
        {({ isSubmitting, dirty, isValid }) => (
          <AuthLayouts.FormBody>
            <AuthLayouts.Message
              title="Account impersonation."
              description={markdown(
                "This feature is only available for `@onyx.app` administrators."
              )}
            />
            <AuthLayouts.Fields>
              <InputVertical title="Email" withLabel="email">
                <InputTypeInField
                  name="email"
                  type="email"
                  placeholder="email@yourcompany.com"
                />
              </InputVertical>
              <InputVertical title="API Key" withLabel="apiKey">
                <PasswordInputTypeInField
                  name="apiKey"
                  placeholder="Enter API Key"
                />
              </InputVertical>
            </AuthLayouts.Fields>
            <AuthLayouts.Submit
              label="impersonate"
              isSubmitting={isSubmitting}
              isValid={isValid}
              dirty={dirty}
            />
          </AuthLayouts.FormBody>
        )}
      </Formik>
    </AuthLayouts.Card>
  );
}
