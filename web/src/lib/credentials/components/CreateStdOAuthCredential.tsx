import * as Yup from "yup";
import { InputTypeIn, MessageCard } from "@opal/components";
import { InputVertical, Section } from "@opal/layouts";
import { Form, Formik, FormikHelpers } from "formik";
import { useState } from "react";
import { useTranslations } from "next-intl";
import type { OAuthAdditionalKwargDescription } from "@/lib/credentials/types";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { ValidSources } from "@/lib/connectors/types/source";
import { FormikField } from "@/refresh-components/form/FormikField";
import { OAuthSignInRow } from "@/lib/credentials/components/OAuthSignInRow";
import { getSourceDisplayName } from "@/lib/sources";

type OAuthFormValues = Record<string, string>;

interface CreateStdOAuthCredentialProps {
  sourceType: ValidSources;
  additionalFields: OAuthAdditionalKwargDescription[];
}

export function CreateStdOAuthCredential({
  sourceType,
  additionalFields,
}: CreateStdOAuthCredentialProps) {
  const t = useTranslations("admin");
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
        error instanceof Error
          ? error.message
          : t("credentials.oauth.startError.message")
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
                withLabel
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
                title={t("credentials.oauth.connectError.title")}
                description={errorMessage}
              />
            )}
            <OAuthSignInRow
              source={getSourceDisplayName(sourceType) || sourceType}
              disabled={isSubmitting}
            />
          </Section>
        </Form>
      )}
    </Formik>
  );
}
