import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider } from "@opal/components";
import { AccessType } from "@/lib/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { submitCredential } from "@/lib/credentials/svc";
import { Form, Formik, FormikHelpers } from "formik";
import { Section, toast } from "@opal/layouts";
import GDriveMain from "@/views/admin/connectors/AddConnectorPage/form/gdrive/GoogleDrivePage";
import type { Connector } from "@/lib/connectors/types";
import type { Credential } from "@/lib/credentials/types";
import { GmailMain } from "@/views/admin/connectors/AddConnectorPage/form/gmail/GmailPage";
import type { CredentialActionType } from "@/lib/credentials/types";
import {
  createValidationSchema,
  getCredentialSpec,
  initialCredentialValues,
} from "@/lib/credentials/utils";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import {
  DEFAULT_SHARE_AUDIENCE,
  ShareAccountField,
  shareAccountPayload,
  type ShareAccountFormValues,
} from "@/lib/credentials/components/ShareAccountField";
import { CredentialFieldsRenderer } from "@/lib/credentials/components/CredentialFieldsRenderer";
import { TypedFile } from "@/lib/connectors/fileTypes";
import { SvgPlusCircle } from "@opal/icons";

interface CreateButtonProps {
  onClick: () => void;
  isSubmitting: boolean;
  /** False while any required field is empty or malformed. */
  isValid: boolean;
}

function CreateButton({ onClick, isSubmitting, isValid }: CreateButtonProps) {
  const t = useTranslations("admin");
  return (
    <Button
      disabled={isSubmitting || !isValid}
      onClick={onClick}
      icon={SvgPlusCircle}
    >
      {t("credentials.create.createButton.label")}
    </Button>
  );
}

type CreateCredentialFormValues = ShareAccountFormValues & {
  [key: string]: unknown;
};

export default function CreateCredential({
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
  const businessTier = useTierAtLeast(Tier.BUSINESS);

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

    const { share, groups, ...credentialValues } = values;

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
        ...shareAccountPayload({ share, groups }),
        // No name: the credential list shows its "Untitled" fallback.
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

  const spec = getCredentialSpec(sourceType);
  if (!spec) {
    return null;
  }
  const validationSchema = createValidationSchema(spec);

  // A spec with auth methods starts on its first one.
  const initialAuthMethod = spec.methods?.[0]?.value;

  return (
    <Formik<CreateCredentialFormValues>
      initialValues={{
        ...initialCredentialValues(spec),
        share: DEFAULT_SHARE_AUDIENCE,
        groups: [],
        ...(initialAuthMethod && {
          authentication_method: initialAuthMethod,
        }),
      }}
      validationSchema={validationSchema}
      // Validate the empty form too, so Create starts disabled.
      validateOnMount
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
          // No card of its own: the form sits directly in its host (the
          // credential step's create card, or a modal).
          <Form className="w-full">
            <Section alignItems="stretch" gap={4}>
              <CredentialFieldsRenderer
                source={sourceType}
                spec={spec}
                authMethod={authMethod || initialAuthMethod}
                setAuthMethod={setAuthMethod}
              />

              {/* Above: the fields the source needs. Below: optional sharing
              and the Create button. */}
              <Divider paddingParallel={0} paddingPerpendicular={0} />

              {businessTier && (
                <ShareAccountField disabled={!formikProps.isValid} />
              )}

              <Section flexDirection="row" justifyContent="end">
                <CreateButton
                  onClick={() =>
                    handleSubmit(
                      formikProps.values,
                      formikProps,
                      swapConnector ? "createAndSwap" : "create"
                    )
                  }
                  isSubmitting={formikProps.isSubmitting}
                  isValid={formikProps.isValid}
                />
              </Section>
            </Section>
          </Form>
        );
      }}
    </Formik>
  );
}
