"use client";

import { useState } from "react";
import { ValidSources, AccessType } from "@/lib/types";
import { submitCredential } from "@/components/admin/connectors/CredentialForm";
import { Form, Formik, FormikHelpers } from "formik";
import { toast } from "@/hooks/useToast";
import GDriveMain from "@/app/admin/connectors/[connector]/pages/gdrive/GoogleDrivePage";
import { Connector } from "@/lib/connectors/connectors";
import {
  Credential,
  credentialTemplates,
  getDisplayNameForCredentialKey,
  CredentialTemplateWithAuth,
} from "@/lib/connectors/credentials";
import { GmailMain } from "@/app/admin/connectors/[connector]/pages/gmail/GmailPage";
import { ActionType, dictionaryType } from "@/components/credentials/types";
import {
  createValidationSchema,
  isOptionalCredentialField,
} from "@/components/credentials/lib";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { AdvancedOptionsToggle } from "@/components/AdvancedOptionsToggle";
import {
  IsPublicGroupSelectorFormType,
  IsPublicGroupSelector,
} from "@/components/IsPublicGroupSelector";
import { useUser } from "@/providers/UserProvider";
import { isTypedFileField, TypedFile } from "@/lib/connectors/fileTypes";
import { BooleanFormField, TypedFileUploadFormField } from "@/components/Field";
import ConnectorDocsLink from "@/components/admin/connectors/ConnectorDocsLink";
import Tabs from "@/refresh-components/Tabs";
import Text from "@/refresh-components/texts/Text";
import { SvgPlusCircle } from "@opal/icons";
import { Button } from "@opal/components";
import * as InputLayouts from "@/layouts/input-layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

type formType = IsPublicGroupSelectorFormType & {
  name: string;
  [key: string]: any; // For additional credential fields
};

export interface CreateCredentialProps {
  // Source information
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
}

export default function CreateCredential({
  sourceType,
  accessType,
  close,
  onClose = () => null,
  onSwitch,
  onSwap = async () => null,
  swapConnector,
  refresh = () => null,
}: CreateCredentialProps) {
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
          toast.success("Created new credential!");
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
        onSwitch(response?.credential!);
      }
    } catch (error) {
      console.error("Error submitting credential:", error);
      toast.error("Error submitting credential");
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

        const templateWithAuth =
          credentialTemplate as CredentialTemplateWithAuth<any>;
        const hasMultipleAuthMethods =
          templateWithAuth.authMethods &&
          templateWithAuth.authMethods.length > 1;

        const handleAuthMethodChange = (newMethod: string) => {
          const cleaned: Record<string, any> = {
            ...formikProps.values,
            authentication_method: newMethod,
          };
          templateWithAuth.authMethods?.forEach((m) => {
            if (m.value !== newMethod) {
              Object.keys(m.fields).forEach((fieldKey) => {
                delete cleaned[fieldKey];
              });
            }
          });
          formikProps.setValues(cleaned as typeof formikProps.values);
          setAuthMethod(newMethod);
        };

        const currentAuthMethod = authMethod || initialAuthMethod;

        return (
          <Form className="w-full flex flex-col gap-4">
            <ConnectorDocsLink sourceType={sourceType} />

            <InputLayouts.Vertical name="name" title="Name" optional>
              <InputTypeInField
                name="name"
                placeholder="Name your credential"
              />
            </InputLayouts.Vertical>

            {hasMultipleAuthMethods && templateWithAuth.authMethods ? (
              <div className="w-full space-y-4">
                <input
                  type="hidden"
                  name="authentication_method"
                  value={
                    currentAuthMethod ||
                    (templateWithAuth.authMethods?.[0]?.value ?? "")
                  }
                />

                <Tabs
                  value={
                    currentAuthMethod ||
                    templateWithAuth.authMethods?.[0]?.value ||
                    ""
                  }
                  onValueChange={handleAuthMethodChange}
                >
                  <Tabs.List>
                    {templateWithAuth.authMethods.map((method) => (
                      <Tabs.Trigger key={method.value} value={method.value}>
                        {method.label}
                      </Tabs.Trigger>
                    ))}
                  </Tabs.List>

                  {templateWithAuth.authMethods.map((method) => (
                    <Tabs.Content
                      key={method.value}
                      value={method.value}
                      alignItems="stretch"
                    >
                      {Object.keys(method.fields).length === 0 &&
                        method.description && (
                          <div className="p-4 bg-background-tint-02 border border-border-02 rounded-md">
                            <Text secondaryBody text03>
                              {method.description}
                            </Text>
                          </div>
                        )}

                      {Object.entries(method.fields).map(([key, val]) => {
                        if (isTypedFileField(key)) {
                          return (
                            <TypedFileUploadFormField
                              key={key}
                              name={key}
                              label={getDisplayNameForCredentialKey(key)}
                            />
                          );
                        }

                        if (typeof val === "boolean") {
                          return (
                            <BooleanFormField
                              key={key}
                              name={key}
                              label={getDisplayNameForCredentialKey(key)}
                            />
                          );
                        }

                        const inputType =
                          key.toLowerCase().includes("token") ||
                          key.toLowerCase().includes("password") ||
                          key.toLowerCase().includes("secret")
                            ? "password"
                            : "text";

                        return (
                          <InputLayouts.Vertical
                            key={key}
                            name={key}
                            title={getDisplayNameForCredentialKey(key)}
                            optional={isOptionalCredentialField(val)}
                          >
                            <InputTypeInField
                              name={key}
                              placeholder={val}
                              type={inputType}
                            />
                          </InputLayouts.Vertical>
                        );
                      })}
                    </Tabs.Content>
                  ))}
                </Tabs>
              </div>
            ) : (
              Object.entries(credentialTemplate).map(([key, val]) => {
                if (key === "authentication_method" || key === "authMethods") {
                  return null;
                }
                if (isTypedFileField(key)) {
                  return (
                    <TypedFileUploadFormField
                      key={key}
                      name={key}
                      label={getDisplayNameForCredentialKey(key)}
                    />
                  );
                }

                if (typeof val === "boolean") {
                  return (
                    <BooleanFormField
                      key={key}
                      name={key}
                      label={getDisplayNameForCredentialKey(key)}
                    />
                  );
                }

                const inputType =
                  key.toLowerCase().includes("token") ||
                  key.toLowerCase().includes("password") ||
                  key.toLowerCase().includes("secret")
                    ? "password"
                    : "text";

                return (
                  <InputLayouts.Vertical
                    key={key}
                    name={key}
                    title={getDisplayNameForCredentialKey(key)}
                    optional={isOptionalCredentialField(val)}
                  >
                    <InputTypeInField
                      name={key}
                      placeholder={val as string}
                      type={inputType}
                    />
                  </InputLayouts.Vertical>
                );
              })
            )}

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
                <Button
                  onClick={() =>
                    handleSubmit(formikProps.values, formikProps, "create")
                  }
                  disabled={
                    formikProps.isSubmitting ||
                    (!isAdmin && formikProps.values.groups.length === 0)
                  }
                  icon={SvgPlusCircle}
                >
                  Create
                </Button>
              </div>
            )}

            {swapConnector && (
              <Button
                onClick={() =>
                  handleSubmit(formikProps.values, formikProps, "createAndSwap")
                }
                disabled={formikProps.isSubmitting}
                icon={SvgPlusCircle}
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
