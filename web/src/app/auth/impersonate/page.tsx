"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "@/i18n/keys";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import { HealthCheckBanner } from "@/components/health/healthcheck";
import { useUser } from "@/components/user/UserProvider";
import { redirect, useRouter } from "next/navigation";
import { Formik, Form, Field } from "formik";
import * as Yup from "yup";
import { usePopup } from "@/components/admin/connectors/Popup";

const ImpersonateSchema = Yup.object().shape({
  email: Yup.string().email("Invalid email").required("Required"),
  apiKey: Yup.string().required("Required"),
});

export default function ImpersonatePage() {
  const { t } = useTranslation();
  const router = useRouter();
  const { user, isCloudSuperuser } = useUser();
  const { popup, setPopup } = usePopup();

  if (!user) {
    redirect("/auth/login");
  }

  if (!isCloudSuperuser) {
    redirect("/search");
  }

  const handleImpersonate = async (values: {
    email: string;
    apiKey: string;
  }) => {
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
      } else {
        router.push("/search");
      }
    } catch (error) {
      setPopup({
        message:
          error instanceof Error ? error.message : "Failed to impersonate user",
        type: "error",
      });
    }
  };

  return (
    <AuthFlowContainer>
      {popup}
      <div className="absolute top-10x w-full">
        <HealthCheckBanner />
      </div>

      <div className="flex flex-col w-full justify-center">
        <h2 className="text-center text-xl text-strong font-bold mb-8">
          {t(k.IMPERSONATE_USER)}
        </h2>

        <Formik
          initialValues={{ email: t(k._1), apiKey: t(k._1) }}
          validationSchema={ImpersonateSchema}
          onSubmit={handleImpersonate}
        >
          {({ errors, touched }) => (
            <Form className="flex flex-col items-stretch gap-y-2">
              <div className="relative">
                <Field
                  type="email"
                  name="email"
                  placeholder={t(k.ENTER_EMAIL_PLACEHOLDER)}
                  className="w-full px-4 py-3 border border-border rounded-lg bg-input focus:outline-none focus:ring-2 focus:ring-primary transition-all duration-200"
                />

                <div className="h-8">
                  {errors.email && touched.email && (
                    <div className="text-red-500 text-sm mt-1">
                      {errors.email}
                    </div>
                  )}
                </div>
              </div>

              <div className="relative">
                <Field
                  type="password"
                  name="apiKey"
                  placeholder={t(k.ENTER_API_KEY_PLACEHOLDER)}
                  className="w-full px-4 py-3 border border-border rounded-lg bg-input focus:outline-none focus:ring-2 focus:ring-primary transition-all duration-200"
                />

                <div className="h-8">
                  {errors.apiKey && touched.apiKey && (
                    <div className="text-red-500 text-sm mt-1">
                      {errors.apiKey}
                    </div>
                  )}
                </div>
              </div>

              <button
                type="submit"
                className="w-full py-3 bg-agent text-white rounded-lg hover:bg-accent/90 transition-colors"
              >
                {t(k.IMPERSONATE_USER)}
              </button>
            </Form>
          )}
        </Formik>

        <div className="text-sm text-text-500 mt-4 text-center px-4 rounded-md">
          {t(k.NOTE_THIS_FEATURE_IS_ONLY_AVA)}
        </div>
      </div>
    </AuthFlowContainer>
  );
}
