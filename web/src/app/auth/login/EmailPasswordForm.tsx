"use client";

import { TextFormField } from "@/components/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { basicLogin, basicSignup } from "@/lib/user";
import Button from "@/refresh-components/buttons/Button";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { requestEmailVerification } from "../lib";
import { useState } from "react";
import { Spinner } from "@/components/Spinner";
import Link from "next/link";
import { useUser } from "@/components/user/UserProvider";

interface EmailPasswordFormProps {
  isSignup?: boolean;
  shouldVerify?: boolean;
  referralSource?: string;
  nextUrl?: string | null;
  defaultEmail?: string | null;
  isJoin?: boolean;
}

export default function EmailPasswordForm({
  isSignup = false,
  shouldVerify,
  referralSource,
  nextUrl,
  defaultEmail,
  isJoin = false,
}: EmailPasswordFormProps) {
  const { user } = useUser();
  const { popup, setPopup } = usePopup();
  const [isWorking, setIsWorking] = useState<boolean>(false);

  return (
    <>
      {isWorking && <Spinner />}
      {popup}

      <Formik
        initialValues={{
          email: defaultEmail ? defaultEmail.toLowerCase() : "",
          password: "",
        }}
        validateOnChange={false}
        validateOnBlur={true}
        validationSchema={Yup.object().shape({
          email: Yup.string()
            .email()
            .required()
            .transform((value) => value.toLowerCase()),
          password: Yup.string().required(),
        })}
        onSubmit={async (values: { email: string; password: string }) => {
          // Ensure email is lowercase
          const email: string = values.email.toLowerCase();

          if (isSignup) {
            // login is fast, no need to show a spinner
            setIsWorking(true);
            const response = await basicSignup(
              email,
              values.password,
              referralSource
            );

            if (!response.ok) {
              setIsWorking(false);

              const errorDetail: any = (await response.json()).detail;
              let errorMsg: string = "Unknown error";
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
            } else {
              setPopup({
                type: "success",
                message: "Account created successfully. Please log in.",
              });
            }
          }

          const loginResponse = await basicLogin(email, values.password);
          if (loginResponse.ok) {
            if (isSignup && shouldVerify) {
              await requestEmailVerification(email);
              // Use window.location.href to force a full page reload,
              // ensuring app re-initializes with the new state (including
              // server-side provider values)
              window.location.href = "/auth/waiting-on-verification";
            } else {
              // The searchparam is purely for multi tenant developement purposes.
              // It replicates the behavior of the case where a user
              // has signed up with email / password as the only user to an instance
              // and has just completed verification
              window.location.href = nextUrl
                ? encodeURI(nextUrl)
                : `/chat${isSignup && !isJoin ? "?new_team=true" : ""}`;
            }
          } else {
            setIsWorking(false);
            const errorDetail: any = (await loginResponse.json()).detail;
            let errorMsg: string = "Unknown error";
            if (errorDetail === "LOGIN_BAD_CREDENTIALS") {
              errorMsg = "Invalid email or password";
            } else if (errorDetail === "NO_WEB_LOGIN_AND_HAS_NO_PASSWORD") {
              errorMsg = "Create an account to set a password";
            } else if (typeof errorDetail === "string") {
              errorMsg = errorDetail;
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
        {({ isSubmitting }) => (
          <Form>
            <TextFormField
              name="email"
              label="Email"
              type="email"
              placeholder="email@yourcompany.com"
              data-testid="email"
            />

            <TextFormField
              name="password"
              label="Password"
              type="password"
              placeholder="**************"
              data-testid="password"
            />

            <Button type="submit" className="w-full" disabled={isSubmitting}>
              {isJoin ? "Join" : isSignup ? "Sign Up" : "Log In"}
            </Button>
            {user?.is_anonymous_user && (
              <Link
                href="/chat"
                className="text-xs text-action-link-05 cursor-pointer text-center w-full font-medium mx-auto"
              >
                <span className="hover:border-b hover:border-dotted hover:border-action-link-05">
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
