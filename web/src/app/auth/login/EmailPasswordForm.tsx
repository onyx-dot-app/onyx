"use client";

import { TextFormField } from "@/components/admin/connectors/Field";
import { usePopup } from "@/components/admin/connectors/Popup";
import { basicLogin, basicSignup } from "@/lib/user";
import { Button } from "@/components/ui/button";
import { Form, Formik } from "formik";
import { useRouter } from "next/navigation";
import * as Yup from "yup";
import { requestEmailVerification } from "../lib";
import { useState } from "react";
import { Spinner } from "@/components/Spinner";


export function EmailPasswordForm({
  isSignup = false,
  shouldVerify,
  referralSource,
}: {
  isSignup?: boolean;
  shouldVerify?: boolean;
  referralSource?: string;
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const [isWorking, setIsWorking] = useState(false);

  let email_subtext = ""
  if (isSignup){
    email_subtext="Signup is restricted to eea domain mail address"
  }
  return (
    <>
      {isWorking && <Spinner />}
      {popup}
      <Formik
        initialValues={{
          email: "",
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
              const errorDetail = (await response.json()).detail;

              let errorMsg = "Unknown error";
              if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
                errorMsg =
                  "An account already exists with the specified email.";
              }
              setPopup({
                type: "error",
                message: `Failed to sign up - ${errorMsg}`,
              });
              return;
            }
          }

          const loginResponse = await basicLogin(values.email, values.password);
          if (loginResponse.ok) {
            window.justLoggedIn = true;
            if (isSignup && shouldVerify) {
              await requestEmailVerification(values.email);
              router.push("/auth/waiting-on-verification");
            } else {
              router.push("/");
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
              subtext={email_subtext}
              placeholder="email@eea.europa.eu"
            />

            <TextFormField
              name="password"
              label="Password"
              type="password"
              placeholder="**************"
            />

            <div className="flex">
              <Button
                type="submit"
                disabled={isSubmitting}
                className="mx-auto w-full"
              >
                {isSignup ? "Sign Up" : "Log In"}
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </>
  );
}
