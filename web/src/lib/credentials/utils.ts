import * as Yup from "yup";

import { credentialTemplates } from "@/lib/connectors/credentials";
import { getDisplayNameForCredentialKey } from "@/lib/connectors/utils";
import type {
  Credential,
  CredentialTemplateWithAuth,
} from "@/lib/connectors/types";
import { isTypedFileField } from "@/lib/connectors/utils";
import type {
  CredentialFieldValues,
  CredentialFormValues,
} from "@/lib/credentials/types";
import { ValidSources } from "@/lib/types";

// What a credential template seeds a field with: "" for a required text
// field, null for an optional one or a file, a boolean for a checkbox.
type CredentialFieldSeed = string | boolean | null;

const AUTHENTICATION_METHOD_KEY = "authentication_method";
const ONEDRIVE_LEGACY_AUTHENTICATION_METHOD_KEY =
  "onedrive_authentication_method";

interface FieldMethods {
  def: CredentialFieldSeed;
  methods: string[];
}

// The rules for one credential field. With `selected` the required rules
// apply only while one of the field's auth methods is chosen.
function fieldSchema(
  key: string,
  def: CredentialFieldSeed,
  selected?: (method: string) => boolean
): Yup.AnySchema {
  const displayName = getDisplayNameForCredentialKey(key);
  if (typeof def === "boolean") {
    return Yup.boolean()
      .nullable()
      .default(false)
      .transform((v, o) => (o === undefined ? false : v));
  }
  if (isTypedFileField(key)) {
    // TypedFile fields use mixed schema instead of string.
    const required = Yup.mixed().required(
      `Please select a ${displayName} file`
    );
    if (!selected) return required;
    return Yup.mixed().when("authentication_method", {
      is: selected,
      then: () => required,
      otherwise: () => Yup.mixed().notRequired(),
    });
  }
  if (def === null) {
    return Yup.string()
      .trim()
      .transform((v) => (v === "" ? null : v))
      .nullable()
      .notRequired();
  }
  const required = (s: Yup.StringSchema) =>
    s
      .min(1, `${displayName} cannot be empty`)
      .required(`Please enter your ${displayName}`);
  if (!selected) return required(Yup.string().trim());
  return Yup.string()
    .trim()
    .when("authentication_method", {
      is: selected,
      then: required,
      otherwise: (s) => s.notRequired(),
    });
}

export function createValidationSchema(jsonValues: Record<string, any>) {
  const schemaFields: Record<string, Yup.AnySchema> = {};
  const template = jsonValues as CredentialTemplateWithAuth<any>;
  // multi-auth templates
  if (template.authMethods && template.authMethods.length > 1) {
    // auth method selector
    schemaFields["authentication_method"] = Yup.string().required(
      "Please select an authentication method"
    );
    // A field several methods share (the app ids of SharePoint and Outlook)
    // is required under every method that lists it, so collect them first.
    const methodsByField = new Map<string, FieldMethods>();
    template.authMethods.forEach((method) => {
      Object.entries(method.fields).forEach(([key, def]) => {
        const entry: FieldMethods = methodsByField.get(key) ?? {
          def,
          methods: [],
        };
        entry.methods.push(method.value);
        methodsByField.set(key, entry);
      });
    });
    methodsByField.forEach(({ def, methods }, key) => {
      schemaFields[key] = fieldSchema(key, def, (method) =>
        methods.includes(method)
      );
    });
  }
  // single-auth templates and other fields
  for (const key in jsonValues) {
    if (!Object.prototype.hasOwnProperty.call(jsonValues, key)) continue;
    if (key === "authentication_method" || key === "authMethods") continue;
    schemaFields[key] = fieldSchema(key, jsonValues[key]);
  }

  schemaFields["name"] = Yup.string().optional();
  return Yup.object().shape(schemaFields);
}

export function createEditingValidationSchema(
  jsonValues: CredentialFieldValues
) {
  const schemaFields: { [key: string]: Yup.AnySchema } = {};

  for (const key in jsonValues) {
    if (Object.prototype.hasOwnProperty.call(jsonValues, key)) {
      if (isTypedFileField(key)) {
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
  credentialTemplate: CredentialTemplateWithAuth<CredentialFieldValues>,
  storedAuthMethod: string | undefined
): CredentialFieldValues {
  const authMethods = credentialTemplate.authMethods ?? [];
  const selectedAuthMethod =
    authMethods.find((method) => method.value === storedAuthMethod) ??
    authMethods.find((method) =>
      Object.keys(method.fields).some((fieldKey) => fieldKey in credentialJson)
    ) ??
    authMethods[0];

  return {
    authentication_method:
      storedAuthMethod ??
      selectedAuthMethod?.value ??
      credentialTemplate.authentication_method ??
      "",
    ...selectedAuthMethod?.fields,
  };
}

function getStoredAuthMethod(
  credentialJson: CredentialFieldValues,
  sourceType: Credential<any>["source"]
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
  credential: Credential<any>,
  sourceType: Credential<any>["source"] = credential.source
): CredentialFieldValues {
  const credentialJson = credential.credential_json ?? {};
  if (isOAuthManagedCredentialJson(credentialJson)) {
    return {};
  }

  const credentialTemplate = credentialTemplates[sourceType] as
    | CredentialFieldValues
    | null
    | undefined;

  if (!credentialTemplate) {
    return credentialJson;
  }

  const templateWithAuth =
    credentialTemplate as CredentialTemplateWithAuth<CredentialFieldValues>;
  const templateFields =
    templateWithAuth.authMethods && templateWithAuth.authMethods.length > 1
      ? getAuthMethodFieldsForCredential(
          credentialJson,
          templateWithAuth,
          getStoredAuthMethod(credentialJson, sourceType)
        )
      : Object.fromEntries(
          Object.entries(credentialTemplate).filter(
            ([key]) => key !== "authMethods"
          )
        );

  return Object.fromEntries(
    Object.entries(templateFields).map(([key, templateValue]) => [
      key,
      credentialJson[key] ?? templateValue,
    ])
  );
}

export function canEditCredentialWithForm(
  credential: Credential<any>,
  sourceType: Credential<any>["source"] = credential.source
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
    if (isTypedFileField(key)) {
      initialValues[key] = null;
    } else {
      initialValues[key] = "";
    }
  }

  return initialValues;
}
