import { ValidSources } from "@/lib/connectors/types/source";
import type {
  CredentialSpec,
  CredentialValidationMessages,
  DraftCredential,
} from "@/lib/credentials/types";
import {
  createValidationSchema,
  getCredentialSpec,
  initialCredentialValues,
} from "@/lib/credentials/utils";
import {
  DEFAULT_SHARE_AUDIENCE,
  shareAccountPayload,
  type ShareAccountFormValues,
} from "@/lib/credentials/components/ShareAccountField";

/**
 * The add-connector form's key for the new account typed into it. The
 * account is part of the form, so Formik validates it with the rest.
 */
export const NEW_ACCOUNT_FIELD = "new_account";

/** The new account's fields, and who may reuse it. */
export type NewAccountValues = ShareAccountFormValues & Record<string, unknown>;

export type NewAccountSchema = ReturnType<typeof createValidationSchema>;

/** Sources with their own account setup instead of typed fields. */
const OWN_ACCOUNT_SETUP: ReadonlySet<ValidSources> = new Set([
  ValidSources.GoogleDrive,
  ValidSources.Gmail,
]);

/**
 * The source's credential spec when a new account is typed into the form;
 * `null` when it is not: Google Drive and Gmail set accounts up their own
 * way, and a file field (a key file) cannot be sent as typed values yet, so
 * those still save an account through the account form.
 */
export function typedAccountSpec(source: ValidSources): CredentialSpec | null {
  if (OWN_ACCOUNT_SETUP.has(source)) return null;
  const spec = getCredentialSpec(source);
  if (!spec) return null;
  const hasFile = Object.values(spec.fields).some(
    (field) => field.kind === "file"
  );
  return hasFile ? null : spec;
}

export function initialNewAccountValues(
  spec: CredentialSpec
): NewAccountValues {
  // A spec with auth methods starts on its first one.
  const authMethod = spec.methods?.[0]?.value;
  return {
    ...initialCredentialValues(spec),
    ...(authMethod !== undefined && { authentication_method: authMethod }),
    share: DEFAULT_SHARE_AUDIENCE,
    groups: [],
  };
}

export function newAccountSchema(
  spec: CredentialSpec,
  messages: CredentialValidationMessages
): NewAccountSchema {
  return createValidationSchema(spec, messages);
}

/**
 * The typed account, when its values are valid; `null` otherwise. Derived
 * from the form's values on each render, so nothing has to report it.
 */
export function typedDraft(
  source: ValidSources,
  schema: NewAccountSchema | null,
  values: NewAccountValues | undefined
): DraftCredential | null {
  if (schema === null || values === undefined || !schema.isValidSync(values)) {
    return null;
  }
  const { share, groups, ...fields } = values;
  return {
    source,
    credential_json: Object.fromEntries(
      Object.entries(fields).filter(
        ([, value]) => value !== null && value !== ""
      )
    ),
    sharing: shareAccountPayload({ share, groups }),
  };
}
