import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Divider } from "@opal/components";
import { AccessType } from "@/lib/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { sealDraftCredential, submitCredential } from "@/lib/credentials/svc";
import { Form, Formik, FormikHelpers, useFormikContext } from "formik";
import { Section, toast } from "@opal/layouts";
import GDriveMain from "@/views/admin/connectors/AddConnectorPage/form/gdrive/GoogleDrivePage";
import type { Connector } from "@/lib/connectors/types";
import type { Credential, DraftCredential } from "@/lib/credentials/types";
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
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
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

/** Waits this long after the last edit before sealing the values. */
const DRAFT_SEAL_DELAY_MS = 500;

interface DraftSealerProps {
  source: ValidSources;
  onDraft: (draft: DraftCredential | null) => void;
}

/**
 * Seals the form's values as a draft whenever they are valid, after typing
 * pauses, and hands the draft up; hands up `null` when they stop being valid
 * and when the form closes. Renders nothing.
 */
function DraftSealer({ source, onDraft }: DraftSealerProps) {
  const t = useTranslations("admin");
  const { values, isValid } = useFormikContext<CreateCredentialFormValues>();
  const { share, groups, ...credentialValues } = values;
  const credentialJson: Record<string, unknown> = Object.fromEntries(
    Object.entries(credentialValues).filter(
      ([, value]) => value !== null && value !== ""
    )
  );
  const valuesKey: string = JSON.stringify(credentialJson);
  const sharing = shareAccountPayload({ share, groups });
  const sharingKey: string = JSON.stringify(sharing);

  // The latest callback, so a seal that lands late reports to the current one.
  const onDraftRef = useRef(onDraft);
  useEffect(() => {
    onDraftRef.current = onDraft;
  });
  // The values the last draft holds, and the draft itself.
  const sealedRef = useRef<{ key: string; draft: DraftCredential } | null>(
    null
  );

  useEffect(() => {
    if (!isValid) {
      if (sealedRef.current !== null) {
        sealedRef.current = null;
        onDraftRef.current(null);
      }
      return;
    }
    const sealed = sealedRef.current;
    if (sealed !== null && sealed.key === valuesKey) {
      // Only the sharing changed: it is not sealed, so no new seal.
      if (JSON.stringify(sealed.draft.sharing) !== sharingKey) {
        const next: DraftCredential = { ...sealed.draft, sharing };
        sealedRef.current = { key: valuesKey, draft: next };
        onDraftRef.current(next);
      }
      return;
    }
    let cancelled = false;
    const timeout = setTimeout(() => {
      sealDraftCredential(source, credentialJson).then(
        (draftCredential) => {
          if (cancelled) return;
          const next: DraftCredential = {
            draft_credential: draftCredential,
            source,
            credential_json: credentialJson,
            sharing,
            sealed_at: new Date().toISOString(),
          };
          sealedRef.current = { key: valuesKey, draft: next };
          onDraftRef.current(next);
        },
        () => {
          if (!cancelled)
            toast.error(t("credentials.create.submitError.toast"));
        }
      );
    }, DRAFT_SEAL_DELAY_MS);
    return () => {
      cancelled = true;
      clearTimeout(timeout);
    };
    // The keys stand for the values; the objects change every render.
  }, [isValid, valuesKey, sharingKey, source]);

  // A closed form's values are gone, so its draft goes too.
  useEffect(() => () => onDraftRef.current(null), []);

  return null;
}

export default function CreateCredential({
  sourceType,
  accessType,
  close,
  onClose = () => null,
  onSwitch,
  onDraft,
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
  // Given, nothing is saved and there is no Create button: once the form is
  // valid, its values are sealed as a draft and handed here, and creating the
  // connector saves it. `null` when the form stops being valid or closes.
  // Sources with a file field (which cannot be sealed yet) still save.
  onDraft?: (draft: DraftCredential | null) => void;
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
  const tValidation = useTranslations("admin.credentials.validation");
  const fieldCopy = useCredentialFieldCopy(sourceType);
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
        // With `onSwitch`, the new credential is picked at once, and the
        // picked credential is the confirmation.
        if (isSuccess) {
          if (!onSwitch) toast.success(message);
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
  const validationSchema = createValidationSchema(spec, {
    fieldTitle: (key) => fieldCopy(key).title,
    required: (field) => tValidation("required", { field }),
    empty: (field) => tValidation("empty", { field }),
    invalidEmail: (field) => tValidation("invalidEmail", { field }),
    fileRequired: (field) => tValidation("fileRequired", { field }),
    authMethodRequired: tValidation("authMethodRequired"),
  });

  // A spec with auth methods starts on its first one.
  const initialAuthMethod = spec.methods?.[0]?.value;
  // A file cannot be sealed, so a source with a file field still saves.
  const sealsDrafts: boolean =
    onDraft !== undefined &&
    !Object.values(spec.fields).some((field) => field.kind === "file");

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
              and the Create button, so with neither there is no divider. */}
              {(businessTier || !sealsDrafts) && (
                <Divider paddingParallel={0} paddingPerpendicular={0} />
              )}

              {businessTier && (
                <ShareAccountField disabled={!formikProps.isValid} />
              )}

              {sealsDrafts && onDraft ? (
                <DraftSealer source={sourceType} onDraft={onDraft} />
              ) : (
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
              )}
            </Section>
          </Form>
        );
      }}
    </Formik>
  );
}
