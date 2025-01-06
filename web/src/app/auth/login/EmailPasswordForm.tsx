"use client";

import { TextFormField } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { basicLogin, basicSignup } from "@/lib/user";
import { Button } from "@/components/ui/button";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { requestEmailVerification } from "../lib";
import { useState } from "react";
import { Spinner } from "@/components/Spinner";
import { set } from "lodash";
import { NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED } from "@/lib/constants";
import Link from "next/link";
import { useUser } from "@/components/user/UserProvider";

export function EmailPasswordForm({
  isSignup = false,
  shouldVerify,
  referralSource,
  nextUrl,
  defaultEmail,
}: {
  isSignup?: boolean;
  shouldVerify?: boolean;
  referralSource?: string;
  nextUrl?: string | null;
  defaultEmail?: string | null;
}) {
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const [isWorking, setIsWorking] = useState(false);
  return (
    <>
      {isWorking && <Spinner />}
      {popup}
      <Formik
        initialValues={{
          email: defaultEmail || "",
          password: "",
        }}
        validationSchema={Yup.object().shape({
          email: Yup.string().email().required(),
          password: Yup.string().required(),
        })}
        onSubmit={async (values) => {
          if (isSignup) {
            // login is fast, no need to show a spinner
            setIsWorking(true);
            const response = await basicSignup(
              values.email,
              values.password,
              referralSource
            );

            if (!response.ok) {
              setIsWorking(false);
              const errorDetail = (await response.json()).detail;
              let errorMsg = "Unknown error";
              if (typeof errorDetail === "object" && errorDetail.reason) {
                errorMsg = errorDetail.reason;
              } else if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
                errorMsg =
                  "An account already exists with the specified email.";
              }
              if (response.status === 429) {
                errorMsg = "Too many requests. Please try again later.";
              }
              setPopup({
                type: "error",
                message: `Failed to sign up - ${errorMsg}`,
              });
              setIsWorking(false);
              return;
            }
          }

          const loginResponse = await basicLogin(values.email, values.password);
          if (loginResponse.ok) {
            if (isSignup && shouldVerify) {
              await requestEmailVerification(values.email);
              // Use window.location.href to force a full page reload,
              // ensuring app re-initializes with the new state (including
              // server-side provider values)
              window.location.href = "/auth/waiting-on-verification";
            } else {
              // See above comment
              window.location.href = nextUrl ? encodeURI(nextUrl) : "/";
            }
          } else {
            setIsWorking(false);
            const errorDetail = (await loginResponse.json()).detail;

            let errorMsg = "Unknown error";
            if (errorDetail === "LOGIN_BAD_CREDENTIALS") {
              errorMsg = "Invalid email or password";
            } else if (errorDetail === "NO_WEB_LOGIN_AND_HAS_NO_PASSWORD") {
              errorMsg = "Create an account to set a password";
            }
            if (loginResponse.status === 429) {
              errorMsg = "Too many requests. Please try again later.";
            }
            setPopup({
              type: "error",
              message: `Failed to login - ${errorMsg}`,
            });
          }
        }}
      >
        {({ isSubmitting, values }) => (
          <Form>
            <TextFormField
              name="email"
              label="Email"
              type="email"
              placeholder="email@yourcompany.com"
            />

            <TextFormField
              name="password"
              label="Password"
              type="password"
              includeForgotPassword={
                NEXT_PUBLIC_FORGOT_PASSWORD_ENABLED && !isSignup
              }
              placeholder="**************"
            />

            <Button
              type="submit"
              disabled={isSubmitting}
              className="mx-auto  !py-4 w-full"
            >
              {isSignup ? "Sign Up" : "Log In"}
            </Button>
            {user?.is_anonymous_user && (
              <Link
                href="/chat"
                className="text-xs text-blue-500  cursor-pointer text-center w-full text-link font-medium mx-auto"
              >
                <span className="hover:border-b hover:border-dotted hover:border-blue-500">
                  or continue as guest
                </span>
              </Link>
            )}
          </Form>
        )}
      </Formik>
    </>
  );
}
