import * as Yup from "yup";

import { Button, InputTypeIn } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { Form, Formik, FormikHelpers } from "formik";

import { OAuthAdditionalKwargDescription } from "@/lib/connectors/credentials";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/oauth";
import { ValidSources } from "@/lib/types";
import { FormikField } from "@/refresh-components/form/FormikField";

type OAuthFormValues = Record<string, string>;

interface CreateStdOAuthCredentialProps {
  sourceType: ValidSources;
  additionalFields: OAuthAdditionalKwargDescription[];
}

export function CreateStdOAuthCredential({
  sourceType,
  additionalFields,
}: CreateStdOAuthCredentialProps) {
  async function handleSubmit(
    values: OAuthFormValues,
    formikHelpers: FormikHelpers<OAuthFormValues>
  ) {
    const errors = await formikHelpers.validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    formikHelpers.setSubmitting(true);
    const redirectUrl = await getConnectorOauthRedirectUrl(sourceType, values);
    if (!redirectUrl) {
      throw new Error("No redirect URL found for OAuth connector");
    }
    window.location.href = redirectUrl;
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
