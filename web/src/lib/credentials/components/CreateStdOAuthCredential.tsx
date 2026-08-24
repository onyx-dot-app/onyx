import * as Yup from "yup";

import { Button, InputTypeIn, MessageCard } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { Form, Formik, FormikHelpers } from "formik";
import { useState } from "react";

import { OAuthAdditionalKwargDescription } from "@/lib/connectors/credentials";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/oauth";
import { ValidSources } from "@/lib/types";
import { FormikField } from "@/refresh-components/form/FormikField";

type OAuthFormValues = Record<string, string>;

const OAUTH_REDIRECT_ERROR = "Unable to start OAuth";

interface CreateStdOAuthCredentialProps {
  sourceType: ValidSources;
  additionalFields: OAuthAdditionalKwargDescription[];
}

export function CreateStdOAuthCredential({
  sourceType,
  additionalFields,
}: CreateStdOAuthCredentialProps) {
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function handleSubmit(
    values: OAuthFormValues,
    formikHelpers: FormikHelpers<OAuthFormValues>
  ) {
    const errors = await formikHelpers.validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    setErrorMessage(null);
    formikHelpers.setSubmitting(true);
    try {
      const redirectUrl = await getConnectorOauthRedirectUrl(
        sourceType,
        values
      );
      window.location.href = redirectUrl;
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : OAUTH_REDIRECT_ERROR
      );
      formikHelpers.setSubmitting(false);
    }
  }

  return (
    <Formik
      initialValues={Object.fromEntries(
        additionalFields.map((field) => [field.name, ""])
      )}
      validationSchema={Yup.object().shape(
        Object.fromEntries(
          additionalFields.map((field) => [field.name, Yup.string().required()])
        )
      )}
      onSubmit={handleSubmit}
    >
      {({ isSubmitting }) => (
        <Form className="w-full">
          <Section alignItems="stretch" gap={6}>
            {additionalFields.map((field) => (
              <InputVertical
                key={field.name}
                withLabel={field.name}
                title={field.display_name}
                description={field.description}
              >
                <FormikField<string>
                  name={field.name}
                  render={(formikField, _helper, _meta, status) => (
                    <InputTypeIn
                      {...formikField}
                      variant={status === "error" ? "error" : "primary"}
                    />
                  )}
                />
              </InputVertical>
            ))}
            {errorMessage && (
              <MessageCard
                variant="error"
                title="Could not connect"
                description={errorMessage}
              />
            )}
            <Section flexDirection="row" justifyContent="start">
              <Button disabled={isSubmitting} type="submit">
                Connect
              </Button>
            </Section>
          </Section>
        </Form>
      )}
    </Formik>
  );
}
