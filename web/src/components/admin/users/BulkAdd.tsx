"use client";

import { useEffect, useCallback, useRef } from "react";
import { Formik, Form, FormikHelpers } from "formik";
import Button from "@/refresh-components/buttons/Button";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { FormikField } from "@/refresh-components/form/FormikField";
import { FormField } from "@/refresh-components/form/FormField";
import { useCaptchaV2 } from "@/lib/hooks/useCaptchaV2";

const WHITESPACE_SPLIT = /\s+/;
const EMAIL_REGEX = /[^@]+@[^.]+\.[^.]/;

interface BulkAddProps {
  onSuccess: () => void;
  onFailure: (res: Response) => void;
}

interface FormValues {
  emails: string;
}

const normalizeEmails = (emails: string) =>
  emails
    .trim()
    .split(WHITESPACE_SPLIT)
    .filter(Boolean)
    .map((email) => email.toLowerCase());

const validate = (values: FormValues) => {
  const errors: Partial<FormValues> = {};
  const emails = normalizeEmails(values.emails);
  if (!emails.length) {
    errors.emails = "Required";
  } else {
    for (const email of emails) {
      if (!email.match(EMAIL_REGEX)) {
        errors.emails = `${email} is not a valid email`;
        break;
      }
    }
  }
  return errors;
};

function BulkAdd({ onSuccess, onFailure }: BulkAddProps) {
  const { isCaptchaEnabled, isLoaded, token, renderCaptcha, resetCaptcha } =
    useCaptchaV2();
  const captchaRendered = useRef(false);

  useEffect(() => {
    if (isCaptchaEnabled && isLoaded && !captchaRendered.current) {
      renderCaptcha("bulk-add-captcha-container");
      captchaRendered.current = true;
    }
  }, [isCaptchaEnabled, isLoaded, renderCaptcha]);

  const handleSubmit = useCallback(
    async (
      values: FormValues,
      { setSubmitting }: FormikHelpers<FormValues>
    ) => {
      const emails = normalizeEmails(values.emails);

      const headers: Record<string, string> = {
        "Content-Type": "application/json",
      };
      if (isCaptchaEnabled && token) {
        headers["X-Captcha-Token"] = token;
      }

      try {
        const res = await fetch("/api/manage/admin/users", {
          method: "PUT",
          headers,
          body: JSON.stringify({ emails }),
        });

        if (res.ok) {
          onSuccess();
        } else {
          resetCaptcha();
          onFailure(res);
        }
      } finally {
        setSubmitting(false);
      }
    },
    [isCaptchaEnabled, token, onSuccess, onFailure, resetCaptcha]
  );

  return (
    <Formik<FormValues>
      initialValues={{ emails: "" }}
      validate={validate}
      onSubmit={handleSubmit}
    >
      {({ isSubmitting, handleSubmit: formikHandleSubmit }) => (
        <Form className="w-full">
          <FormikField<string>
            name="emails"
            render={(field, _helper, meta, state) => (
              <FormField name="emails" state={state}>
                <FormField.Control>
                  <InputTextArea
                    {...field}
                    variant={state === "error" ? "error" : "primary"}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        formikHandleSubmit();
                      }
                    }}
                  />
                </FormField.Control>
                <FormField.Message
                  messages={{
                    idle: "",
                    error: meta.error,
                    success: "",
                  }}
                />
              </FormField>
            )}
          />
          {isCaptchaEnabled && (
            <div id="bulk-add-captcha-container" className="mt-4" />
          )}
          <Button
            type="submit"
            disabled={isSubmitting || (isCaptchaEnabled && !token)}
            className="self-end"
          >
            Add
          </Button>
        </Form>
      )}
    </Formik>
  );
}

export default BulkAdd;
