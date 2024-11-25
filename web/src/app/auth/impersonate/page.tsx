"use client";
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
  const router = useRouter();
  const { user, isLoadingUser, isCloudSuperuser } = useUser();
  const { popup, setPopup } = usePopup();

  if (isLoadingUser) {
    return null;
  }

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
          Impersonate User
        </h2>

        <Formik
          initialValues={{ email: "", apiKey: "" }}
          validationSchema={ImpersonateSchema}
          onSubmit={handleImpersonate}
        >
          {({ errors, touched }) => (
            <Form className="flex flex-col items-stretch gap-y-2">
              <div className="relative">
                <Field
                  type="email"
                  name="email"
                  placeholder="Enter user email to impersonate"
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
                  placeholder="Enter API Key"
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
                className="w-full py-3 bg-accent text-white rounded-lg hover:bg-accent/90 transition-colors"
              >
                Impersonate User
              </button>
            </Form>
          )}
        </Formik>

        <div className="text-sm text-text-500 mt-4 text-center px-4 rounded-md">
          Note: This feature is only available for @danswer.ai administrators
        </div>
      </div>
    </AuthFlowContainer>
  );
}
