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
import Text from "@/refresh-components/texts/Text";

const ImpersonateSchema = Yup.object().shape({
  email: Yup.string().email("邮箱格式无效").required("必填"),
  apiKey: Yup.string().required("必填"),
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
        toast.error(errorData.detail || "冒充用户失败");
        helpers.setSubmitting(false);
      } else {
        helpers.setSubmitting(false);
        router.push("/app" as Route);
      }
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : "冒充用户失败"
      );
      helpers.setSubmitting(false);
    }
  };

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="w-full flex flex-col items-center justify-center">
          <Text as="p" headingH3 className="mb-6 text-center">
            冒充用户
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
                label="邮箱"
                placeholder="email@yourcompany.com"
              />

              <TextFormField
                name="apiKey"
                type="password"
                label="API Key"
                placeholder="输入 API Key"
              />

              <Button disabled={isSubmitting} type="submit" width="full">
                冒充用户
              </Button>
            </Form>
          )}
        </Formik>

        <Text
          as="p"
          mainUiMuted
          text03
          className="mt-4 text-center px-4"
        >{`注意：此功能仅面向 @glomi.ai 管理员开放`}</Text>
      </div>
    </AuthFlowContainer>
  );
}
