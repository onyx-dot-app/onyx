import * as Yup from "yup";

import {
  Credential,
  CredentialTemplateWithAuth,
  credentialTemplates,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import { isTypedFileField } from "@/lib/connectors/fileTypes";
import type {
  CredentialFieldValues,
  CredentialFormValues,
} from "@/lib/credentials/types";

export function createValidationSchema(jsonValues: Record<string, any>) {
  const schemaFields: Record<string, Yup.AnySchema> = {};
  const template = jsonValues as CredentialTemplateWithAuth<any>;
  // multi-auth templates
  if (template.authMethods && template.authMethods.length > 1) {
    // auth method selector
    schemaFields["authentication_method"] = Yup.string().required(
      "Please select an authentication method"
    );
    // conditional rules per authMethod
    template.authMethods.forEach((method) => {
      Object.entries(method.fields).forEach(([key, def]) => {
        const displayName = getDisplayNameForCredentialKey(key);
        if (typeof def === "boolean") {
          schemaFields[key] = Yup.boolean()
            .nullable()
            .default(false)
            .transform((v, o) => (o === undefined ? false : v));
        } else if (isTypedFileField(key)) {
          // TypedFile fields use mixed schema instead of string.
          schemaFields[key] = Yup.mixed().when("authentication_method", {
            is: method.value,
            then: () =>
              Yup.mixed().required(`Please select a ${displayName} file`),
            otherwise: () => Yup.mixed().notRequired(),
          });
        } else if (def === null) {
          schemaFields[key] = Yup.string()
            .trim()
            .transform((v) => (v === "" ? null : v))
            .nullable()
            .notRequired();
        } else {
          schemaFields[key] = Yup.string()
            .trim()
            .when("authentication_method", {
              is: method.value,
              then: (s) =>
                s
                  .min(1, `${displayName} cannot be empty`)
                  .required(`Please enter your ${displayName}`),
              otherwise: (s) => s.notRequired(),
            });
        }
      });
    });
  }
  // single-auth templates and other fields
  for (const key in jsonValues) {
    if (!Object.prototype.hasOwnProperty.call(jsonValues, key)) continue;
    if (key === "authentication_method" || key === "authMethods") continue;
    const displayName = getDisplayNameForCredentialKey(key);
    const def = jsonValues[key];
    if (typeof def === "boolean") {
      schemaFields[key] = Yup.boolean()
        .nullable()
        .default(false)
        .transform((v, o) => (o === undefined ? false : v));
    } else if (isTypedFileField(key)) {
      // TypedFile fields use mixed schema instead of string.
      schemaFields[key] = Yup.mixed().required(
        `Please select a ${displayName} file`
      );
    } else if (def === null) {
      schemaFields[key] = Yup.string()
        .trim()
        .transform((v) => (v === "" ? null : v))
        .nullable()
        .notRequired();
    } else {
      schemaFields[key] = Yup.string()
        .trim()
        .min(1, `${displayName} cannot be empty`)
        .required(`Please enter your ${displayName}`);
    }
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
  credentialTemplate: CredentialTemplateWithAuth<CredentialFieldValues>
): CredentialFieldValues {
  const authMethods = credentialTemplate.authMethods ?? [];
  const storedAuthMethod =
    typeof credentialJson.authentication_method === "string"
      ? credentialJson.authentication_method
      : undefined;
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
      ? getAuthMethodFieldsForCredential(credentialJson, templateWithAuth)
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
