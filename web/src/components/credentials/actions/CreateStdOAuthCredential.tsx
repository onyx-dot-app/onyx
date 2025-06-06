import * as Yup from "yup";

import React from "react";
import { Button } from "@/components/ui/button";
import { ValidSources } from "@/lib/types";
import { TextFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import CardSection from "@/components/admin/CardSection";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/oauth";
import { OAuthAdditionalKwargDescription } from "@/lib/connectors/credentials";

type formType = {
  [key: string]: any; // For additional credential fields
};

export function CreateStdOAuthCredential({
  sourceType,
  additionalFields,
}: {
  // Source information
  sourceType: ValidSources;

  additionalFields: OAuthAdditionalKwargDescription[];
}) {
  const handleSubmit = async (
    values: formType,
    formikHelpers: FormikHelpers<formType>
  ) => {
    const { setSubmitting, validateForm } = formikHelpers;

    const errors = await validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    setSubmitting(true);
    formikHelpers.setSubmitting(true);

    const redirectUrl = await getConnectorOauthRedirectUrl(sourceType, values);

    if (!redirectUrl) {
      throw new Error("No redirect URL found for OAuth connector");
    }

    window.location.href = redirectUrl;
  };

  return (
    <Formik
      initialValues={
        {
          ...Object.fromEntries(additionalFields.map((field) => [field, ""])),
        } as formType
      }
      validationSchema={Yup.object().shape({
        ...Object.fromEntries(
          additionalFields.map((field) => [field.name, Yup.string().required()])
        ),
      })}
      onSubmit={(values, formikHelpers) => {
        handleSubmit(values, formikHelpers);
      }}
    >
      {() => (
        <Form className="w-full flex items-stretch">
          <CardSection className="w-full !border-0 mt-4 flex flex-col gap-y-6">
            {additionalFields.map((field) => (
              <TextFormField
                key={field.name}
                name={field.name}
                label={field.display_name}
                subtext={field.description}
                type="text"
              />
            ))}

            <div className="flex w-full">
              <Button type="submit" className="flex text-sm">
                Create
              </Button>
            </div>
          </CardSection>
        </Form>
      )}
    </Formik>
  );
}
