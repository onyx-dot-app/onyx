"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../i18n/keys";
import React, { JSX, useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Popup } from "./Popup";
import { ValidSources } from "@/lib/types";

import { createCredential } from "@/lib/credential";
import { CredentialBase, Credential } from "@/lib/connectors/credentials";

export async function submitCredential<T>(
  credential: CredentialBase<T>,
  t: (key: string, params?: any) => string
): Promise<{
  credential?: Credential<any>;
  message: string;
  isSuccess: boolean;
}> {
  let isSuccess = false;
  try {
    const response = await createCredential(credential);

    if (response.ok) {
      const parsed_response = await response.json();
      const credential = parsed_response.credential;
      isSuccess = true;
      return { credential, message: t(k.SUCCESS1), isSuccess: true };
    } else {
      const errorData = await response.json();
      return {
        message: t(k.ERROR_WITH_DETAIL, { detail: errorData.detail }),
        isSuccess: false,
      };
    }
  } catch (error) {
    return { message: t(k.ERROR_GENERIC, { error }), isSuccess: false };
  }
}

interface Props<YupObjectType extends Yup.AnyObject> {
  formBody: JSX.Element | null;
  validationSchema: Yup.ObjectSchema<YupObjectType>;
  initialValues: YupObjectType;
  onSubmit: (isSuccess: boolean) => void;
  source: ValidSources;
}

export function CredentialForm<T extends Yup.AnyObject>({
  formBody,
  validationSchema,
  initialValues,
  source,
  onSubmit,
}: Props<T>): JSX.Element {
  const { t } = useTranslation();
  const [popup, setPopup] = useState<{
    message: string;
    type: "success" | "error";
  } | null>(null);

  return (
    <>
      {popup && <Popup message={popup.message} type={popup.type} />}
      <Formik
        initialValues={initialValues}
        validationSchema={validationSchema}
        onSubmit={(values, formikHelpers) => {
          formikHelpers.setSubmitting(true);
          submitCredential<T>({
            credential_json: values,
            admin_public: true,
            curator_public: false,
            groups: [],
            source: source,
          }, t).then(({ message, isSuccess }) => {
            setPopup({ message, type: isSuccess ? "success" : "error" });
            formikHelpers.setSubmitting(false);
            setTimeout(() => {
              setPopup(null);
            }, 4000);
            onSubmit(isSuccess);
          });
        }}
      >
        {({ isSubmitting }) => (
          <Form>
            {formBody}
            <div className="flex">
              <button
                type="submit"
                color="green"
                disabled={isSubmitting}
                className="mx-auto w-64 inline-flex items-center 
                justify-center whitespace-nowrap rounded-md text-sm 
                font-medium transition-colors  bg-background-200 text-primary-foreground
                focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring 
                disabled:pointer-events-none disabled:opacity-50 
                shadow hover:bg-primary/90 h-9 px-4 py-2"
              >
                {t(k.UPDATE)}
              </button>
            </div>
          </Form>
        )}
      </Formik>
    </>
  );
}
