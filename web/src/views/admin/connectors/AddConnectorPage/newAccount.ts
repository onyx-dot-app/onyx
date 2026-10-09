import { getIn } from "formik";
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
  realmFields,
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

/** The new account's display name, kept apart from its credential values. */
export const NEW_ACCOUNT_NAME_FIELD = "name";

/** The new account's fields, its display name, and who may reuse it. */
export type NewAccountValues = ShareAccountFormValues & {
  name: string;
} & Record<string, unknown>;

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

/**
 * The spec's fields the new account asks for itself. Its realm is a
 * credential-bound field above the account section, under the same key.
 */
function ownFieldsSpec(spec: CredentialSpec): CredentialSpec {
  return {
    ...spec,
    fields: Object.fromEntries(
      Object.entries(spec.fields).filter(([, field]) => !field.realm)
    ),
  };
}

export function initialNewAccountValues(
  spec: CredentialSpec
): NewAccountValues {
  // A spec with auth methods starts on its first one.
  const authMethod = spec.methods?.[0]?.value;
  return {
    ...initialCredentialValues(ownFieldsSpec(spec)),
    ...(authMethod !== undefined && { authentication_method: authMethod }),
    name: "",
    share: DEFAULT_SHARE_AUDIENCE,
    groups: [],
  };
}

export function newAccountSchema(
  spec: CredentialSpec,
  messages: CredentialValidationMessages
): NewAccountSchema {
  return createValidationSchema(ownFieldsSpec(spec), messages);
}

/**
 * The typed account, when its values are valid; `null` otherwise. Its realm
 * comes from the credential-bound field of the same key in `formValues`, as
 * the connectors read it from the credential. Derived from the form's values
 * on each render, so nothing has to report it.
 */
export function typedDraft(
  source: ValidSources,
  schema: NewAccountSchema | null,
  formValues: Readonly<Record<string, unknown>>
): DraftCredential | null {
  const values: NewAccountValues | undefined = getIn(
    formValues,
    NEW_ACCOUNT_FIELD
  );
  const spec = typedAccountSpec(source);
  if (
    spec === null ||
    schema === null ||
    values === undefined ||
    !schema.isValidSync(values)
  ) {
    return null;
  }
  const realm: Record<string, string> = {};
  for (const [key, field] of realmFields(spec)) {
    const value = formValues[key];
    if (typeof value === "string" && value.trim() !== "") {
      realm[key] = value.trim();
    } else if (!field.optional) {
      return null;
    }
  }
  const { share, groups, name, ...fields } = values;
  return {
    source,
    credential_json: {
      ...Object.fromEntries(
        Object.entries(fields).filter(
          ([, value]) => value !== null && value !== ""
        )
      ),
      ...realm,
    },
    sharing: {
      ...shareAccountPayload({ share, groups }),
      // Blank leaves the account untitled.
      name: name.trim() || null,
    },
  };
}
