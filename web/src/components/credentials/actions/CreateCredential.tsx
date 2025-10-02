import React, { useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { ValidSources, AccessType } from "@/lib/types";
import { FaAccusoft } from "react-icons/fa";
import { submitCredential } from "@/components/admin/connectors/CredentialForm";
import { TextFormField } from "@/components/Field";
import { Form, Formik, FormikHelpers } from "formik";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import GDriveMain from "@/app/admin/connectors/[connector]/pages/gdrive/GoogleDrivePage";
import { Connector } from "@/lib/connectors/connectors";
import { Credential, credentialTemplates } from "@/lib/connectors/credentials";
import { GmailMain } from "@/app/admin/connectors/[connector]/pages/gmail/GmailPage";
import { ActionType, dictionaryType } from "../types";
import { createValidationSchema } from "../lib";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import {
  IsPublicGroupSelectorFormType,
  IsPublicGroupSelector,
} from "@/components/IsPublicGroupSelector";
import { useUser } from "@/components/user/UserProvider";
import CardSection from "@/components/admin/CardSection";
import { CredentialFieldsRenderer } from "./CredentialFieldsRenderer";
import { TypedFile } from "@/lib/connectors/fileTypes";
import ConnectorDocsLink from "@/components/admin/connectors/ConnectorDocsLink";
import SvgPlusCircle from "@/icons/plus-circle";

const CreateButton = ({
  onClick,
  isSubmitting,
  isAdmin,
  groups,
}: {
  onClick: () => void;
  isSubmitting: boolean;
  isAdmin: boolean;
  groups: number[];
}) => (
  <Button
    onClick={onClick}
    disabled={isSubmitting || (!isAdmin && groups.length === 0)}
    leftIcon={SvgPlusCircle}
  >
    Create
  </Button>
);

type formType = IsPublicGroupSelectorFormType & {
  name: string;
  [key: string]: any; // For additional credential fields
};

export default function CreateCredential({
  hideSource,
  sourceType,
  accessType,
  setPopup,
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
  setPopup: (popupSpec: PopupSpec | null) => void;

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
  const [showAdvancedOptions, setShowAdvancedOptions] = useState(false);
  const [authMethod, setAuthMethod] = useState<string>();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const { isAdmin } = useUser();

  const handleSubmit = async (
    values: formType,
    formikHelpers: FormikHelpers<formType>,
    action: ActionType
  ) => {
    const { setSubmitting, validateForm } = formikHelpers;

    const errors = await validateForm(values);
    if (Object.keys(errors).length > 0) {
      formikHelpers.setErrors(errors);
      return;
    }

    setSubmitting(true);
    formikHelpers.setSubmitting(true);

    const { name, is_public, groups, ...credentialValues } = values;

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
        curator_public: is_public,
        groups: groups,
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
          setPopup({ type: "success", message: "Created new credential!" });
          setTimeout(() => setPopup(null), 4000);
        }
        onClose();
      } else {
        setPopup({ message, type: isSuccess ? "success" : "error" });
      }

      if (close) {
        onClose();
      }
      await refresh();

      if (onSwitch) {
        onSwitch(response?.credential!);
      }
    } catch (error) {
      console.error("Error submitting credential:", error);
      setPopup({ message: "Error submitting credential", type: "error" });
    } finally {
      formikHelpers.setSubmitting(false);
    }
  };

  if (sourceType == "gmail") {
    return <GmailMain />;
  }

  if (sourceType == "google_drive") {
    return <GDriveMain setPopup={setPopup} />;
  }

  const credentialTemplate: dictionaryType = credentialTemplates[sourceType];
  const validationSchema = createValidationSchema(credentialTemplate);

  // Set initial auth method for templates with multiple auth methods
  const templateWithAuth = credentialTemplate as any;
  const initialAuthMethod =
    templateWithAuth?.authMethods?.[0]?.value || undefined;

  return (
    <Formik
      initialValues={
        {
          name: "",
          is_public: isAdmin || !isPaidEnterpriseFeaturesEnabled,
          groups: [],
          ...(initialAuthMethod && {
            authentication_method: initialAuthMethod,
          }),
        } as formType
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
                placeholder="(Optional) credential name.."
                label="Name:"
              />

              <CredentialFieldsRenderer
                credentialTemplate={credentialTemplate}
                authMethod={authMethod || initialAuthMethod}
                setAuthMethod={setAuthMethod}
              />

              {!swapConnector && (
                <div className="mt-4 flex w-full flex-col sm:flex-row justify-between items-end">
                  <div className="w-full sm:w-3/4 mb-4 sm:mb-0">
                    {isPaidEnterpriseFeaturesEnabled && (
                      <div className="flex flex-col items-start">
                        {isAdmin && (
                          <AdvancedOptionsToggle
                            showAdvancedOptions={showAdvancedOptions}
                            setShowAdvancedOptions={setShowAdvancedOptions}
                          />
                        )}
                        {(showAdvancedOptions || !isAdmin) && (
                          <IsPublicGroupSelector
                            formikProps={formikProps}
                            objectName="credential"
                            publicToWhom="Curators"
                          />
                        )}
                      </div>
                    )}
                  </div>
                  <CreateButton
                    onClick={() =>
                      handleSubmit(formikProps.values, formikProps, "create")
                    }
                    isSubmitting={formikProps.isSubmitting}
                    isAdmin={isAdmin}
                    groups={formikProps.values.groups}
                  />
                </div>
              )}
            </CardSection>
            {swapConnector && (
              <Button
                className="bg-rose-500 hover:bg-rose-400"
                onClick={() =>
                  handleSubmit(formikProps.values, formikProps, "createAndSwap")
                }
                disabled={formikProps.isSubmitting}
                leftIcon={() => (
                  <FaAccusoft className="fill-text-inverted-05" />
                )}
              >
                Create
              </Button>
            )}
          </Form>
        );
      }}
    </Formik>
  );
}
