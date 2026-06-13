"use client";
import React, { useState } from "react";
import { forgotPassword } from "./utils";
import AuthFlowContainer from "@/components/auth/AuthFlowContainer";
import Title from "@/components/ui/title";
import { Text } from "@opal/components";
import { markdown } from "@opal/utils";
import { Spacer } from "@opal/components";
import Link from "next/link";
import { Button } from "@opal/components";
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
          <Title className="mb-2 mx-auto font-bold">忘记密码</Title>
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
              toast.success("密码重置邮件已发送，请检查你的收件箱。");
            } catch (error) {
              const errorMessage =
                error instanceof Error
                  ? error.message
                  : "发生错误，请稍后重试。";
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
                label="邮箱"
                type="email"
                placeholder="email@yourcompany.com"
              />

              <div className="flex">
                <Button disabled={isSubmitting} type="submit" width="full">
                  重置密码
                </Button>
              </div>
            </Form>
          )}
        </Formik>
        <Spacer rem={1} />
        <div className="flex">
          <div className="mx-auto">
            <Text as="p">{markdown("[返回登录](/auth/login)")}</Text>
          </div>
        </div>
      </div>
    </AuthFlowContainer>
  );
};

export default ForgotPasswordPage;
