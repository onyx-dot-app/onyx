"use client";

import Link from "next/link";
import { Form, Formik } from "formik";
import * as Yup from "yup";
import { useMemo, useState } from "react";

import { Spinner } from "@/components/Spinner";
import { toast } from "@/hooks/useToast";
import { validateInternalRedirect } from "@/lib/auth/redirectValidation";
import { useCaptcha } from "@/lib/hooks/useCaptcha";
import { basicLogin, basicSignup } from "@/lib/user";
import { useUser } from "@/providers/UserProvider";
import Button from "@/refresh-components/buttons/Button";
import { FormField } from "@/refresh-components/form/FormField";
import { FormikField } from "@/refresh-components/form/FormikField";
import { APIFormFieldState } from "@/refresh-components/form/types";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";

import { requestEmailVerification } from "../lib";

const AUTH_INPUT_CLASSNAME =
  "!rounded-12 !border-[color:var(--landing-border)] !bg-[color:var(--landing-card-solid)] !text-[var(--landing-text)] p-4 transition-colors duration-200 placeholder:!text-[var(--landing-muted)] hover:!border-[color:var(--landing-border-strong)] focus-within:!border-[color:var(--landing-accent)] focus-within:!shadow-none";

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
  const { user, authTypeMetadata } = useUser();
  const passwordMinLength = authTypeMetadata?.passwordMinLength ?? 8;
  const [isWorking, setIsWorking] = useState<boolean>(false);
  const [apiStatus, setApiStatus] = useState<APIFormFieldState>("loading");
  const [showApiMessage, setShowApiMessage] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string>("");
  const { getCaptchaToken } = useCaptcha();

  const apiMessages = useMemo(
    () => ({
      loading: isSignup
        ? isJoin
          ? "Uniendote..."
          : "Creando cuenta..."
        : "Ingresando...",
      success: isSignup
        ? isJoin
          ? "Acceso listo. Ingresando..."
          : "Cuenta creada. Ingresando..."
        : "Sesion iniciada correctamente.",
      error: errorMessage,
    }),
    [isSignup, isJoin, errorMessage]
  );

  return (
    <>
      {isWorking && <Spinner />}

      <Formik
        initialValues={{
          email: defaultEmail ? defaultEmail.toLowerCase() : "",
          password: "",
        }}
        validateOnChange={true}
        validateOnBlur={true}
        validationSchema={Yup.object().shape({
          email: Yup.string()
            .email("Ingresa un correo valido")
            .required("El correo es obligatorio")
            .transform((value) => value.toLowerCase()),
          password: Yup.string()
            .min(
              passwordMinLength,
              `La contrasena debe tener al menos ${passwordMinLength} caracteres`
            )
            .required("La contrasena es obligatoria"),
        })}
        onSubmit={async (values: { email: string; password: string }) => {
          const email: string = values.email.toLowerCase();
          setShowApiMessage(true);
          setApiStatus("loading");
          setErrorMessage("");

          if (isSignup) {
            setIsWorking(true);

            const captchaToken = await getCaptchaToken("signup");

            const response = await basicSignup(
              email,
              values.password,
              referralSource,
              captchaToken
            );

            if (!response.ok) {
              setIsWorking(false);

              const errorDetail: any = (await response.json()).detail;
              let errorMsg: string = "Error desconocido";
              if (typeof errorDetail === "object" && errorDetail.reason) {
                errorMsg = errorDetail.reason;
              } else if (errorDetail === "REGISTER_USER_ALREADY_EXISTS") {
                errorMsg = "Ya existe una cuenta con este correo.";
              }
              if (response.status === 429) {
                errorMsg = "Demasiados intentos. Intentalo de nuevo mas tarde.";
              }
              setErrorMessage(errorMsg);
              setApiStatus("error");
              toast.error(`No se pudo crear la cuenta - ${errorMsg}`);
              return;
            }

            setApiStatus("success");
            toast.success("Cuenta creada correctamente. Ahora inicia sesion.");
          }

          const loginResponse = await basicLogin(email, values.password);
          if (loginResponse.ok) {
            setApiStatus("success");
            if (isSignup && shouldVerify) {
              await requestEmailVerification(email);
              window.location.href = "/auth/waiting-on-verification";
            } else {
              const validatedNextUrl = validateInternalRedirect(nextUrl);
              window.location.href = validatedNextUrl
                ? validatedNextUrl
                : `/app${isSignup && !isJoin ? "?new_team=true" : ""}`;
            }
            return;
          }

          setIsWorking(false);
          const errorDetail: any = (await loginResponse.json()).detail;
          let errorMsg: string = "Error desconocido";
          if (errorDetail === "LOGIN_BAD_CREDENTIALS") {
            errorMsg = "Credenciales invalidas";
          } else if (errorDetail === "NO_WEB_LOGIN_AND_HAS_NO_PASSWORD") {
            errorMsg = "Crea una cuenta para configurar tu contrasena";
          } else if (typeof errorDetail === "string") {
            errorMsg = errorDetail;
          }
          if (loginResponse.status === 429) {
            errorMsg = "Demasiados intentos. Intentalo de nuevo mas tarde.";
          }
          setErrorMessage(errorMsg);
          setApiStatus("error");
          toast.error(`No se pudo iniciar sesion - ${errorMsg}`);
        }}
      >
        {({ isSubmitting, isValid, dirty }) => (
          <Form className="flex w-full flex-col gap-4">
            <FormikField<string>
              name="email"
              render={(field, helper, meta, state) => (
                <FormField name="email" state={state} className="w-full">
                  <FormField.Label className="pb-1 text-[11px] font-semibold uppercase tracking-[0.18em] !text-[var(--landing-accent-strong)]">
                    Correo
                  </FormField.Label>
                  <FormField.Control>
                    <InputTypeIn
                      {...field}
                      onChange={(e) => {
                        if (showApiMessage && apiStatus === "error") {
                          setShowApiMessage(false);
                          setErrorMessage("");
                          setApiStatus("loading");
                        }
                        field.onChange(e);
                      }}
                      placeholder="correo@tuempresa.com"
                      onClear={() => helper.setValue("")}
                      data-testid="email"
                      variant={apiStatus === "error" ? "error" : undefined}
                      showClearButton={false}
                      className={AUTH_INPUT_CLASSNAME}
                    />
                  </FormField.Control>
                  {meta.touched && meta.error && !showApiMessage && (
                    <FormField.Message
                      messages={{
                        error: meta.error,
                      }}
                    />
                  )}
                </FormField>
              )}
            />

            <FormikField<string>
              name="password"
              render={(field, helper, meta, state) => (
                <FormField name="password" state={state} className="w-full">
                  <FormField.Label className="pb-1 text-[11px] font-semibold uppercase tracking-[0.18em] !text-[var(--landing-accent-strong)]">
                    Contrasena
                  </FormField.Label>
                  <FormField.Control>
                    <PasswordInputTypeIn
                      {...field}
                      onChange={(e) => {
                        if (showApiMessage && apiStatus === "error") {
                          setShowApiMessage(false);
                          setErrorMessage("");
                          setApiStatus("loading");
                        }
                        field.onChange(e);
                      }}
                      placeholder="Ingresa tu contrasena"
                      onClear={() => helper.setValue("")}
                      data-testid="password"
                      error={apiStatus === "error"}
                      showClearButton={false}
                      className={AUTH_INPUT_CLASSNAME}
                    />
                  </FormField.Control>
                  {isSignup && !showApiMessage && (
                    <FormField.Message
                      messages={{
                        idle: `La contrasena debe tener al menos ${passwordMinLength} caracteres`,
                        error: meta.error,
                        success: `La contrasena debe tener al menos ${passwordMinLength} caracteres`,
                      }}
                    />
                  )}
                  {!isSignup && meta.touched && meta.error && !showApiMessage && (
                    <FormField.Message
                      messages={{
                        error: meta.error,
                      }}
                    />
                  )}
                  {showApiMessage && (
                    <FormField.APIMessage
                      state={apiStatus}
                      messages={apiMessages}
                    />
                  )}
                </FormField>
              )}
            />

            <div className="pt-2">
              <Button
                type="submit"
                main
                primary
                className="w-full justify-center rounded-full !border !border-[color:var(--landing-accent)] !bg-[var(--landing-accent)] px-6 py-3 !shadow-[0_18px_45px_-24px_rgba(51,108,250,0.7)] hover:!border-[color:var(--landing-accent-strong)] hover:!bg-[var(--landing-accent-strong)] disabled:cursor-not-allowed disabled:!border-[color:var(--landing-border)] disabled:!bg-[color:var(--landing-surface-alt)]"
                disabled={isSubmitting || !isValid || !dirty}
              >
                {isJoin ? "Unirme" : isSignup ? "Crear cuenta" : "Entrar"}
              </Button>
            </div>

            {user?.is_anonymous_user && (
              <Link
                href="/app"
                className="mx-auto w-full cursor-pointer text-center text-xs font-medium text-[var(--landing-accent)]"
              >
                <span className="hover:border-b hover:border-dotted hover:border-[color:var(--landing-accent)]">
                  o continuar como invitado
                </span>
              </Link>
            )}
          </Form>
        )}
      </Formik>
    </>
  );
}
