import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button as OpalButton } from "@opal/components";
import { ValidSources, AccessType } from "@/lib/types";
import { submitCredential } from "@/components/admin/connectors/CredentialForm";
import { TextFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { toast } from "@opal/layouts";
import GDriveMain from "@/app/admin/connectors/[connector]/pages/gdrive/GoogleDrivePage";
import { Connector } from "@/lib/connectors/connectors";
import {
  Credential,
  CredentialTemplateWithAuth,
  credentialTemplates,
} from "@/lib/connectors/credentials";
import { GmailMain } from "@/app/admin/connectors/[connector]/pages/gmail/GmailPage";
import type {
  CredentialActionType,
  CredentialFieldValues,
} from "@/lib/credentials/types";
import { createValidationSchema } from "@/lib/credentials/utils";
import CardSection from "@/components/admin/CardSection";
import { CredentialFieldsRenderer } from "@/lib/credentials/components/CredentialFieldsRenderer";
import { TypedFile } from "@/lib/connectors/fileTypes";
import ConnectorDocsLink from "@/components/admin/connectors/ConnectorDocsLink";
import { SvgPlusCircle } from "@opal/icons";
const CreateButton = ({
  onClick,
  isSubmitting,
}: {
  onClick: () => void;
  isSubmitting: boolean;
}) => {
  const t = useTranslations("admin");
  return (
    <OpalButton disabled={isSubmitting} onClick={onClick} icon={SvgPlusCircle}>
      {t("credentials.create.createButton.label")}
    </OpalButton>
  );
};

type CreateCredentialFormValues = {
  name: string;
  [key: string]: unknown;
};

export default function CreateCredential({
  hideSource,
  sourceType,
  accessType,
  close,
  onClose = () => null,
  onSwitch,
  onSwap = async () => null,
  swapConnector,
  refresh = () => null,
}: {
  // Source information
  hideSource?: boolean; // hides docs link
  sourceType: ValidSources;
  accessType: AccessType;

  // Optional toggle- close section after selection?
  close?: boolean;

  // Special handlers
  onClose?: () => void;
  // Switch currently selected credential
  onSwitch?: (selectedCredential: Credential<any>) => Promise<void>;
  // Switch currently selected credential + link with connector
  onSwap?: (
    selectedCredential: Credential<any>,
    connectorId: number,
    accessType: AccessType
  ) => void;

  // For swapping credentials on selection
  swapConnector?: Connector<any>;

  // Mutating parent state
  refresh?: () => void;
}) {
  const t = useTranslations("admin");
  const [authMethod, setAuthMethod] = useState<string>();

  const handleSubmit = async (
    values: CreateCredentialFormValues,
    formikHelpers: FormikHelpers<CreateCredentialFormValues>,
    action: CredentialActionType
  ) => {
    const { setSubmitting, validateForm } = formikHelpers;

    const errors = await validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    setSubmitting(true);
    formikHelpers.setSubmitting(true);

    const { name, ...credentialValues } = values;

    let privateKey: TypedFile | null = null;
    const filteredCredentialValues = Object.fromEntries(
      Object.entries(credentialValues).filter(([key, value]) => {
        if (value instanceof TypedFile) {
          privateKey = value;
          return false;
        }
        return value !== null && value !== "";
      })
    );

    try {
      const response = await submitCredential({
        credential_json: filteredCredentialValues,
        admin_public: true,
        name: name,
        source: sourceType,
        private_key: privateKey || undefined,
      });

      const { message, isSuccess, credential } = response;

      if (!credential) {
        throw new Error("No credential returned");
      }

      if (isSuccess && swapConnector) {
        if (action === "createAndSwap") {
          onSwap(credential, swapConnector.id, accessType);
        } else {
          toast.success(t("credentials.create.created.toast"));
        }
        onClose();
      } else {
        if (isSuccess) {
          toast.success(message);
        } else {
          toast.error(message);
        }
      }

      if (close) {
        onClose();
      }
      await refresh();

      if (onSwitch) {
        onSwitch(credential);
      }
    } catch (error) {
      console.error("Error submitting credential:", error);
      toast.error(t("credentials.create.submitError.toast"));
    } finally {
      formikHelpers.setSubmitting(false);
    }
  };

  if (sourceType == "gmail") {
    return <GmailMain />;
  }

  if (sourceType == "google_drive") {
    return <GDriveMain />;
  }

  const credentialTemplate: CredentialFieldValues =
    credentialTemplates[sourceType];
  const validationSchema = createValidationSchema(credentialTemplate);

  // Set initial auth method for templates with multiple auth methods
  const templateWithAuth =
    credentialTemplate as CredentialTemplateWithAuth<CredentialFieldValues>;
  const initialAuthMethod =
    templateWithAuth?.authMethods?.[0]?.value || undefined;

  return (
    <Formik
      initialValues={
        {
          name: "",
          ...(initialAuthMethod && {
            authentication_method: initialAuthMethod,
          }),
        } as CreateCredentialFormValues
      }
      validationSchema={validationSchema}
      onSubmit={() => {}} // This will be overridden by our custom submit handlers
    >
      {(formikProps) => {
        // Update authentication_method in formik when authMethod changes
        if (
          authMethod &&
          formikProps.values.authentication_method !== authMethod
        ) {
          formikProps.setFieldValue("authentication_method", authMethod);
        }

        return (
          <Form className="w-full flex items-stretch">
            {!hideSource && <ConnectorDocsLink sourceType={sourceType} />}
            <CardSection className="w-full items-start dark:bg-neutral-900 mt-4 flex flex-col gap-y-6">
              <TextFormField
                name="name"
                placeholder={t("credentials.create.name.placeholder")}
                label={t("credentials.create.name.label")}
              />

              <CredentialFieldsRenderer
                credentialTemplate={credentialTemplate}
                authMethod={authMethod || initialAuthMethod}
                setAuthMethod={setAuthMethod}
              />

              <div className="mt-4 flex w-full justify-end">
                <CreateButton
                  onClick={() =>
                    handleSubmit(
                      formikProps.values,
                      formikProps,
                      swapConnector ? "createAndSwap" : "create"
                    )
                  }
                  isSubmitting={formikProps.isSubmitting}
                />
              </div>
            </CardSection>
          </Form>
        );
      }}
    </Formik>
  );
}
