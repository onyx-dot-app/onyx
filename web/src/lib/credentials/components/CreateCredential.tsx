import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider, InputSingleSelect } from "@opal/components";
import { AccessType } from "@/lib/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { submitCredential } from "@/lib/credentials/svc";
import { Form, Formik, FormikHelpers, type FormikProps } from "formik";
import { InputHorizontal, Section, toast } from "@opal/layouts";
import { Disabled } from "@opal/core";
import GDriveMain from "@/views/admin/connectors/AddConnectorPage/form/gdrive/GoogleDrivePage";
import type { Connector } from "@/lib/connectors/types";
import { CREDENTIAL_TEMPLATES } from "@/lib/credentials/constants";
import type {
  Credential,
  CredentialTemplateWithAuth,
} from "@/lib/credentials/types";
import { GmailMain } from "@/views/admin/connectors/AddConnectorPage/form/gmail/GmailPage";
import type {
  CredentialActionType,
  CredentialFieldValues,
} from "@/lib/credentials/types";
import { createValidationSchema } from "@/lib/credentials/utils";
import { useTierAtLeast } from "@/hooks/useTierAtLeast";
import { Tier } from "@/lib/settings/types";
import type { IsPublicGroupSelectorFormType } from "@/components/IsPublicGroupSelector";
import { useUserGroups } from "@/lib/hooks";
import { CredentialFieldsRenderer } from "@/lib/credentials/components/CredentialFieldsRenderer";
import { TypedFile } from "@/lib/connectors/fileTypes";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { SvgPlusCircle, SvgUserManage, SvgUsers } from "@opal/icons";
const SHARE_ADMINS = "admins";
const SHARE_EVERYONE = "everyone";
const SHARE_GROUP_PREFIX = "group:";

interface ShareAccountFieldProps {
  formikProps: FormikProps<CreateCredentialFormValues>;
  /** Only a global connector manager may share with everyone. */
  isGlobalHolder: boolean;
}

/**
 * Who may reuse the new credential: admins only, everyone, or one user
 * group. One select over the form's `is_public` and `groups`, disabled until
 * the rest of the form is valid.
 */
function ShareAccountField({
  formikProps,
  isGlobalHolder,
}: ShareAccountFieldProps) {
  const t = useTranslations("admin");
  const { data: userGroups } = useUserGroups();
  const { is_public: isPublic, groups } = formikProps.values;

  const value = isPublic
    ? SHARE_EVERYONE
    : groups[0] !== undefined
      ? `${SHARE_GROUP_PREFIX}${groups[0]}`
      : SHARE_ADMINS;

  function handleValueChange(next: string) {
    if (next === SHARE_EVERYONE) {
      formikProps.setFieldValue("is_public", true);
      formikProps.setFieldValue("groups", []);
    } else if (next.startsWith(SHARE_GROUP_PREFIX)) {
      formikProps.setFieldValue("is_public", false);
      formikProps.setFieldValue("groups", [
        Number(next.slice(SHARE_GROUP_PREFIX.length)),
      ]);
    } else {
      formikProps.setFieldValue("is_public", false);
      formikProps.setFieldValue("groups", []);
    }
  }

  // Until the account's own fields are filled in, the whole row is
  // unavailable: title and description dim along with the select.
  return (
    <Disabled disabled={!formikProps.isValid}>
      <InputHorizontal
        withLabel="share"
        title={t("credentials.create.share.title")}
        description={t("credentials.create.share.description")}
        center
      >
        <InputSingleSelect
          value={value}
          onValueChange={handleValueChange}
          defaultOption={SHARE_ADMINS}
          placeholder={t("credentials.create.share.title")}
          disabled={!formikProps.isValid}
          options={[
            {
              value: SHARE_ADMINS,
              title: t("credentials.create.share.admins.label"),
              icon: SvgUserManage,
            },
            ...(isGlobalHolder
              ? [
                  {
                    value: SHARE_EVERYONE,
                    title: t("credentials.create.share.everyone.label"),
                    icon: SvgUsers,
                  },
                ]
              : []),
            ...(userGroups ?? []).map((group) => ({
              value: `${SHARE_GROUP_PREFIX}${group.id}`,
              title: group.name,
              icon: SvgUsers,
            })),
          ]}
        />
      </InputHorizontal>
    </Disabled>
  );
}

interface CreateButtonProps {
  onClick: () => void;
  isSubmitting: boolean;
  /** False while any required field is empty or malformed. */
  isValid: boolean;
  // Only a scoped manager must land the credential in a group — GATE 2 requires
  // it of them and of nobody else.
  requiresGroup: boolean;
  groups: number[];
}

function CreateButton({
  onClick,
  isSubmitting,
  isValid,
  requiresGroup,
  groups,
}: CreateButtonProps) {
  const t = useTranslations("admin");
  return (
    <Button
      disabled={
        isSubmitting || !isValid || (requiresGroup && groups.length === 0)
      }
      onClick={onClick}
      icon={SvgPlusCircle}
    >
      {t("credentials.create.createButton.label")}
    </Button>
  );
}

type CreateCredentialFormValues = IsPublicGroupSelectorFormType & {
  name: string;
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

  const { isGlobalHolder, isScopedManager } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );

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
    CREDENTIAL_TEMPLATES[sourceType];
  const validationSchema = createValidationSchema(credentialTemplate);

  // Set initial auth method for templates with multiple auth methods
  const templateWithAuth =
    credentialTemplate as CredentialTemplateWithAuth<CredentialFieldValues>;
  const initialAuthMethod =
    templateWithAuth?.authMethods?.[0]?.value || undefined;

  return (
    <Formik<CreateCredentialFormValues>
      initialValues={{
        name: "",
        is_public: isGlobalHolder || !businessTier,
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
                credentialTemplate={credentialTemplate}
                authMethod={authMethod || initialAuthMethod}
                setAuthMethod={setAuthMethod}
              />

              {/* Above: the fields the source needs. Below: optional sharing
              and the Create button. */}
              <Divider paddingParallel={0} paddingPerpendicular={0} />

              {businessTier && (
                <ShareAccountField
                  formikProps={formikProps}
                  isGlobalHolder={isGlobalHolder}
                />
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
                  requiresGroup={isScopedManager}
                  groups={formikProps.values.groups}
                />
              </Section>
            </Section>
          </Form>
        );
      }}
    </Formik>
  );
}
