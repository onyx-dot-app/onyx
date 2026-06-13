"use client";
import React, { useState, useEffect } from "react";
import { resetPassword } from "../forgot-password/utils";
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
import { redirect, useSearchParams } from "next/navigation";
import {
  NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED,
  TENANT_ID_COOKIE_NAME,
} from "@/lib/constants";
import Cookies from "js-cookie";

const ResetPasswordPage: React.FC = () => {
  const [isWorking, setIsWorking] = useState(false);
  const searchParams = useSearchParams();
  const token = searchParams?.get("token");
  const tenantId = searchParams?.get(TENANT_ID_COOKIE_NAME);
  // Keep search param same name as cookie for simplicity

  useEffect(() => {
    if (tenantId) {
      Cookies.set(TENANT_ID_COOKIE_NAME, tenantId, {
        path: "/",
        expires: 1 / 24,
      }); // Expires in 1 hour
    }
  }, [tenantId]);

  if (!NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED) {
    redirect("/auth/login");
  }

  return (
    <AuthFlowContainer>
      <div className="flex flex-col w-full justify-center">
        <div className="flex">
          <Title className="mb-2 mx-auto font-bold">重置密码</Title>
        </div>
        {isWorking && <Spinner />}
        <Formik
          initialValues={{
            password: "",
            confirmPassword: "",
          }}
          validationSchema={Yup.object().shape({
            password: Yup.string().required("请输入密码"),
            confirmPassword: Yup.string()
              .oneOf([Yup.ref("password"), undefined], "两次输入的密码必须一致")
              .required("请确认密码"),
          })}
          onSubmit={async (values) => {
            if (!token) {
              toast.error("重置 token 无效或缺失。");
              return;
            }
            setIsWorking(true);
            try {
              await resetPassword(token, values.password);
              toast.success(
                "密码已重置。正在跳转到登录页..."
              );
              setTimeout(() => {
                redirect("/auth/login");
              }, 1000);
            } catch (error) {
              if (error instanceof Error) {
                toast.error(
                  error.message || "重置密码时发生错误。"
                );
              } else {
                toast.error("发生意外错误。请重试。");
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
                label="新密码"
                type="password"
                placeholder="输入新密码"
              />
              <TextFormField
                name="confirmPassword"
                label="确认新密码"
                type="password"
                placeholder="再次输入新密码"
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

export default ResetPasswordPage;
