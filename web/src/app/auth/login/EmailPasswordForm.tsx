"use client";

import { TextFormField } from "@/components/admin/connectors/Field";
import { basicLogin, basicSignup } from "@/lib/user";
import { Form, Formik } from "formik";
import { useRouter } from "next/navigation";
import * as Yup from "yup";
import { requestEmailVerification } from "../lib";
import { useState } from "react";
import { Spinner } from "@/components/Spinner";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";

export function EmailPasswordForm({
  isSignup = false,
  shouldVerify,
}: {
  isSignup?: boolean;
  shouldVerify?: boolean;
}) {
  const router = useRouter();
  const { toast } = useToast();
  const [isWorking, setIsWorking] = useState(false);

  return (
    <>
      {isWorking && <Spinner />}
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
            const response = await basicSignup(values.email, values.password);

            if (!response.ok) {
              const errorDetail = (await response.json()).detail;

              let errorMsg = "Unknown error";
              if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
                errorMsg =
                  "An account already exists with the specified email.";
              }
              toast({
                title: "Error",
                description: `Failed to sign up - ${errorMsg}`,
                variant: "destructive",
              });
              return;
            }
          }

          const loginResponse = await basicLogin(values.email, values.password);
          if (loginResponse.ok) {
            if (isSignup && shouldVerify) {
              await requestEmailVerification(values.email);
              router.push("/auth/waiting-on-verification");
            } else {
              router.push("/chat");
            }
          } else {
            setIsWorking(false);
            const errorDetail = (await loginResponse.json()).detail;

            let errorMsg = "Unknown error";
            if (errorDetail === "LOGIN_BAD_CREDENTIALS") {
              errorMsg = "Invalid email or password";
            }
            toast({
              title: "Error",
              description: `Failed to login - ${errorMsg}`,
              variant: "destructive",
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
              placeholder="**************"
            />

            <div className="flex">
              <Button type="submit" disabled={isSubmitting} className="w-full">
                {isSignup ? "Sign Up" : "Log In"}
              </Button>
            </div>
          </Form>
        )}
      </Formik>
    </>
  );
}
