"use client";

import * as Yup from "yup";
import { ValidSources } from "@/lib/types";
import { Form, Formik, FormikHelpers } from "formik";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/oauth";
import { OAuthAdditionalKwargDescription } from "@/lib/connectors/credentials";
import { Button } from "@opal/components";
import { SvgPlusCircle } from "@opal/icons";
import * as InputLayouts from "@/layouts/input-layouts";
import * as GeneralLayouts from "@/layouts/general-layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

type formType = {
  [key: string]: any;
};

export interface CreateStdOAuthCredentialProps {
  sourceType: ValidSources;
  additionalFields: OAuthAdditionalKwargDescription[];
}

export default function CreateStdOAuthCredential({
  sourceType,
  additionalFields,
}: CreateStdOAuthCredentialProps) {
  async function handleSubmit(
    values: formType,
    formikHelpers: FormikHelpers<formType>
  ) {
    const { setSubmitting, validateForm } = formikHelpers;

    const errors = await validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    setSubmitting(true);

    const redirectUrl = await getConnectorOauthRedirectUrl(sourceType, values);

    if (!redirectUrl) {
      throw new Error("No redirect URL found for OAuth connector");
    }

    window.location.href = redirectUrl;
  }

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
      onSubmit={handleSubmit}
    >
      {() => (
        <Form>
          <GeneralLayouts.Section>
            {additionalFields.map((field) => (
              <InputLayouts.Vertical
                key={field.name}
                name={field.name}
                title={field.display_name}
                description={field.description}
              >
                <InputTypeInField name={field.name} />
              </InputLayouts.Vertical>
            ))}

            <Button type="submit" icon={SvgPlusCircle}>
              Create
            </Button>
          </GeneralLayouts.Section>
        </Form>
      )}
    </Formik>
  );
}
