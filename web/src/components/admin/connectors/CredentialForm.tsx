import React, { useState } from "react";
import { Formik, Form } from "formik";
import * as Yup from "yup";
import { Popup } from "./Popup";
import { ValidSources } from "@/lib/types";

import {
  createCredential,
  createCredentialWithPrivateKey,
} from "@/lib/credential";
import {
  CredentialBase,
  Credential,
  CredentialWithPrivateKey,
} from "@/lib/connectors/credentials";

const PRIVATE_KEY_FIELD_KEY = "private_key";

export async function submitCredential<T>(
  credential: CredentialBase<T> | CredentialWithPrivateKey<T>
): Promise<{
  credential?: Credential<any>;
  message: string;
  isSuccess: boolean;
}> {
  let isSuccess = false;
  try {
    let response: Response;
    if (PRIVATE_KEY_FIELD_KEY in credential && credential.private_key) {
      response = await createCredentialWithPrivateKey(
        credential as CredentialWithPrivateKey<T>
      );
    } else {
      response = await createCredential(credential as CredentialBase<T>);
    }
    if (response.ok) {
      const parsed_response = await response.json();
      const credential = parsed_response.credential;
      isSuccess = true;
      return { credential, message: "Success!", isSuccess: true };
    } else {
      const errorData = await response.json();
      return { message: `Error: ${errorData.detail}`, isSuccess: false };
    }
  } catch (error) {
    return { message: `Error: ${error}`, isSuccess: false };
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
          }).then(({ message, isSuccess }) => {
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
                Update
              </button>
            </div>
          </Form>
        )}
      </Formik>
    </>
  );
}
