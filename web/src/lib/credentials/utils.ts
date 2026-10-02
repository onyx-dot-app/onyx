import * as Yup from "yup";

import type { Credential } from "@/lib/credentials/types";
import type {
  CredentialFieldValues,
  CredentialFormValues,
} from "@/lib/credentials/types";
import { ValidSources } from "@/lib/connectors/types/source";
import { toast } from "@opal/layouts";
import {
  CredentialCreationMethod,
  type OAuthDetails,
} from "@/lib/credentials/types";
import type {
  CredentialSpec,
  CredentialSpecField,
  CredentialSpecMethod,
  CredentialValidationMessages,
} from "@/lib/credentials/types";
import type { FileTypeCategory } from "@/lib/connectors/types/fileTypes";
import { CREDENTIAL_SPECS } from "@/lib/credentials/constants";

// ---------------------------------------------------------------------------
// Credential specs
// ---------------------------------------------------------------------------

/** A source's spec, or null when it has no credential form. */
export function getCredentialSpec(source: ValidSources): CredentialSpec | null {
  return CREDENTIAL_SPECS[source];
}

const FILE_FIELD_TYPES: ReadonlyMap<string, FileTypeCategory> = new Map(
  Object.values<CredentialSpec | null>(CREDENTIAL_SPECS).flatMap((spec) =>
    Object.entries(spec?.fields ?? {}).flatMap(([key, field]) => {
      if (field.kind !== "file") return [];
      const entry: [string, FileTypeCategory] = [key, field.fileType];
      return [entry];
    })
  )
);

/** The file type a credential field takes, or null when it takes text. */
export function getCredentialFileType(key: string): FileTypeCategory | null {
  return FILE_FIELD_TYPES.get(key) ?? null;
}

/** The value a form starts a field at. */
export function initialFieldValue(
  field: CredentialSpecField
): string | boolean | null {
  if (field.kind === "toggle" || field.kind === "checkbox") return false;
  if (field.kind === "file" || field.optional) return null;
  return "";
}

/** A method's fields, in the order the method lists them. */
export function methodFields(
  spec: CredentialSpec,
  method: CredentialSpecMethod
): [string, CredentialSpecField][] {
  return method.fields.flatMap((key) => {
    const field = spec.fields[key];
    if (!field) return [];
    const entry: [string, CredentialSpecField] = [key, field];
    return [entry];
  });
}

/** The value of each field a form starts with. */
export function initialCredentialValues(
  spec: CredentialSpec
): CredentialFieldValues {
  return Object.fromEntries(
    Object.entries(spec.fields).map(([key, field]) => [
      key,
      initialFieldValue(field),
    ])
  );
}

// ---------------------------------------------------------------------------
// Validation and edit forms
// ---------------------------------------------------------------------------

const AUTHENTICATION_METHOD_KEY = "authentication_method";
const ONEDRIVE_LEGACY_AUTHENTICATION_METHOD_KEY =
  "onedrive_authentication_method";

// The rules for one credential field. With `selected` the required rules
// apply only while one of the field's auth methods is chosen.
function fieldSchema(
  key: string,
  field: CredentialSpecField,
  messages: CredentialValidationMessages,
  selected?: (method: string) => boolean
): Yup.AnySchema {
  const title = messages.fieldTitle(key);
  if (field.kind === "toggle" || field.kind === "checkbox") {
    return Yup.boolean()
      .nullable()
      .default(false)
      .transform((v, o) => (o === undefined ? false : v));
  }
  if (field.kind === "file") {
    // TypedFile fields use mixed schema instead of string.
    const required = Yup.mixed().required(messages.fileRequired(title));
    if (!selected) return required;
    return Yup.mixed().when(AUTHENTICATION_METHOD_KEY, {
      is: selected,
      then: () => required,
      otherwise: () => Yup.mixed().notRequired(),
    });
  }
  const base =
    field.kind === "email"
      ? Yup.string().trim().email(messages.invalidEmail(title))
      : Yup.string().trim();
  if (field.optional) {
    return base
      .transform((v) => (v === "" ? null : v))
      .nullable()
      .notRequired();
  }
  const required = (s: Yup.StringSchema) =>
    s.min(1, messages.empty(title)).required(messages.required(title));
  if (!selected) return required(base);
  return base.when(AUTHENTICATION_METHOD_KEY, {
    is: selected,
    then: required,
    otherwise: (s) => s.notRequired(),
  });
}

export function createValidationSchema(
  spec: CredentialSpec,
  messages: CredentialValidationMessages
) {
  const schemaFields: Record<string, Yup.AnySchema> = {};
  const methods = spec.methods;
  if (methods) {
    schemaFields[AUTHENTICATION_METHOD_KEY] = Yup.string().required(
      messages.authMethodRequired
    );
  }
  for (const [key, field] of Object.entries(spec.fields)) {
    // A field several methods share (the Microsoft app ids) is required
    // under every method that lists it.
    const fieldMethods = methods
      ?.filter((method) => method.fields.includes(key))
      .map((method) => method.value);
    schemaFields[key] = fieldSchema(
      key,
      field,
      messages,
      fieldMethods && ((method) => fieldMethods.includes(method))
    );
  }
  return Yup.object().shape(schemaFields);
}

export function createEditingValidationSchema(
  jsonValues: CredentialFieldValues
) {
  const schemaFields: { [key: string]: Yup.AnySchema } = {};

  for (const key in jsonValues) {
    if (Object.prototype.hasOwnProperty.call(jsonValues, key)) {
      if (getCredentialFileType(key) !== null) {
        // TypedFile fields use mixed schema for optional file uploads during editing.
        schemaFields[key] = Yup.mixed().optional();
      } else {
        schemaFields[key] = Yup.string().optional();
      }
    }
  }

  schemaFields["name"] = Yup.string().optional();
  return Yup.object().shape(schemaFields);
}

function getAuthMethodFieldsForCredential(
  credentialJson: CredentialFieldValues,
  spec: CredentialSpec,
  methods: readonly CredentialSpecMethod[],
  storedAuthMethod: string | undefined
): CredentialFieldValues {
  const selectedAuthMethod =
    methods.find((method) => method.value === storedAuthMethod) ??
    methods.find((method) =>
      method.fields.some((fieldKey) => fieldKey in credentialJson)
    ) ??
    methods[0];

  return {
    authentication_method: storedAuthMethod ?? selectedAuthMethod?.value ?? "",
    ...Object.fromEntries(
      (selectedAuthMethod ? methodFields(spec, selectedAuthMethod) : []).map(
        ([key, field]) => [key, initialFieldValue(field)]
      )
    ),
  };
}

function getStoredAuthMethod(
  credentialJson: CredentialFieldValues,
  sourceType: ValidSources
): string | undefined {
  const standardMethod = credentialJson[AUTHENTICATION_METHOD_KEY];
  if (typeof standardMethod === "string") {
    return standardMethod;
  }
  const legacyMethod =
    sourceType === ValidSources.OneDrive
      ? credentialJson[ONEDRIVE_LEGACY_AUTHENTICATION_METHOD_KEY]
      : undefined;
  return typeof legacyMethod === "string" ? legacyMethod : undefined;
}

const OAUTH_MANAGED_CREDENTIAL_KEYS = new Set([
  "expires_at",
  "expires_in",
  "refresh_token",
  "token_type",
]);

function isOAuthManagedCredentialJson(
  credentialJson: CredentialFieldValues
): boolean {
  return Object.keys(credentialJson).some(
    (key) =>
      OAUTH_MANAGED_CREDENTIAL_KEYS.has(key) ||
      key.endsWith("_refresh_token") ||
      key.endsWith("_expires_at") ||
      key.endsWith("_expires_in")
  );
}

export function getEditableCredentialFields(
  credential: Credential<CredentialFieldValues>,
  sourceType: ValidSources = credential.source
): CredentialFieldValues {
  const credentialJson = credential.credential_json ?? {};
  if (isOAuthManagedCredentialJson(credentialJson)) {
    return {};
  }

  const spec = getCredentialSpec(sourceType);
  if (!spec) {
    return credentialJson;
  }

  const templateFields: CredentialFieldValues = spec.methods
    ? getAuthMethodFieldsForCredential(
        credentialJson,
        spec,
        spec.methods,
        getStoredAuthMethod(credentialJson, sourceType)
      )
    : Object.fromEntries(
        Object.entries(spec.fields).map(([key, field]) => [
          key,
          initialFieldValue(field),
        ])
      );
  // The edit form types every field as text, so it leaves out checkboxes and
  // switches; their stored values stay as they are.
  for (const [key, field] of Object.entries(spec.fields)) {
    if (field.kind === "checkbox" || field.kind === "toggle") {
      delete templateFields[key];
    }
  }

  return Object.fromEntries(
    Object.entries(templateFields).map(([key, templateValue]) => [
      key,
      credentialJson[key] ?? templateValue,
    ])
  );
}

export function canEditCredentialWithForm(
  credential: Credential<any>,
  sourceType: ValidSources = credential.source
): boolean {
  return (
    Object.keys(getEditableCredentialFields(credential, sourceType)).length > 0
  );
}

export function createInitialValues(
  credential: Credential<any>,
  credentialFields: CredentialFieldValues = credential.credential_json
): CredentialFormValues {
  const initialValues: CredentialFormValues = {
    name: credential.name || "",
  };

  for (const key in credentialFields) {
    // Initialize TypedFile fields as null, other fields as empty strings
    if (getCredentialFileType(key) !== null) {
      initialValues[key] = null;
    } else {
      initialValues[key] = "";
    }
  }

  return initialValues;
}

// Parse an uploaded OAuth app JSON; toasts and returns null when invalid.
export const parseOauthAppCredentialJson = (
  value: string
): Record<string, unknown> | null => {
  try {
    const parsed = JSON.parse(value) as Record<string, unknown>;
    const web = parsed.web as Record<string, unknown> | undefined;
    if (
      !web ||
      typeof web.client_id !== "string" ||
      typeof web.client_secret !== "string"
    ) {
      toast.error(
        "Invalid file provided - expected an OAuth app JSON key with web.client_id and web.client_secret"
      );
      return null;
    }
    return parsed;
  } catch (error) {
    toast.error(`Invalid file provided - ${error}`);
    return null;
  }
};

export const filterUploadedCredentials = <
  T extends { authentication_method?: string },
>(
  credentials: Credential<T>[] | undefined
): { credential_id: number | null; uploadedCredentials: Credential<T>[] } => {
  let credential_id = null;
  let uploadedCredentials: Credential<T>[] = [];

  if (credentials) {
    uploadedCredentials = credentials.filter(
      (credential) =>
        credential.credential_json.authentication_method !== "oauth_interactive"
    );

    if (uploadedCredentials.length > 0 && uploadedCredentials[0]) {
      credential_id = uploadedCredentials[0].id;
    }
  }

  return { credential_id, uploadedCredentials };
};

// ---------------------------------------------------------------------------
// Credential creation methods
// ---------------------------------------------------------------------------

export function getCredentialCreationMethods(
  details?: OAuthDetails
): CredentialCreationMethod[] {
  if (!details) {
    return [CredentialCreationMethod.Manual];
  }

  const methods: CredentialCreationMethod[] = [];
  if (details.oauth_enabled) {
    methods.push(CredentialCreationMethod.OAuth);
  }
  if (details.supports_manual_credentials) {
    methods.push(CredentialCreationMethod.Manual);
  }
  return methods;
}

export function getCredentialCreationActionLabel(
  method: CredentialCreationMethod,
  sourceDisplayName: string,
  explicitMethod: boolean
): string {
  if (!explicitMethod) {
    return "Create New";
  }
  return method === CredentialCreationMethod.OAuth
    ? `Connect with ${sourceDisplayName}`
    : "Enter credentials manually";
}

export function shouldRedirectToOAuth(details: OAuthDetails): boolean {
  return details.additional_kwargs.length === 0;
}
