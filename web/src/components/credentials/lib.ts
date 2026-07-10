import * as Yup from "yup";

import { dictionaryType, formType } from "./types";
import {
  Credential,
  CredentialTemplateWithAuth,
  credentialTemplates,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";
import { isTypedFileField } from "@/lib/connectors/fileTypes";

export function createValidationSchema(json_values: Record<string, any>) {
  const schemaFields: Record<string, Yup.AnySchema> = {};
  const template = json_values as CredentialTemplateWithAuth<any>;
  // multi‐auth templates
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
          //TypedFile fields - use mixed schema instead of string (check before null check)
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
  // single‐auth templates and other fields
  for (const key in json_values) {
    if (!Object.prototype.hasOwnProperty.call(json_values, key)) continue;
    if (key === "authentication_method" || key === "authMethods") continue;
    const displayName = getDisplayNameForCredentialKey(key);
    const def = json_values[key];
    if (typeof def === "boolean") {
      schemaFields[key] = Yup.boolean()
        .nullable()
        .default(false)
        .transform((v, o) => (o === undefined ? false : v));
    } else if (isTypedFileField(key)) {
      // TypedFile fields - use mixed schema instead of string (check before null check)
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

export function createEditingValidationSchema(json_values: dictionaryType) {
  const schemaFields: { [key: string]: Yup.AnySchema } = {};

  for (const key in json_values) {
    if (Object.prototype.hasOwnProperty.call(json_values, key)) {
      if (isTypedFileField(key)) {
        // TypedFile fields - use mixed schema for optional file uploads during editing
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
  credentialJson: dictionaryType,
  credentialTemplate: CredentialTemplateWithAuth<dictionaryType>
): dictionaryType {
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

export function getEditableCredentialFields(
  credential: Credential<any>,
  sourceType: Credential<any>["source"] = credential.source
): dictionaryType {
  const credentialJson = credential.credential_json ?? {};
  const credentialTemplate = credentialTemplates[sourceType] as
    | dictionaryType
    | null
    | undefined;

  if (!credentialTemplate) {
    return credentialJson;
  }

  const templateWithAuth =
    credentialTemplate as CredentialTemplateWithAuth<dictionaryType>;
  const templateFields =
    templateWithAuth.authMethods && templateWithAuth.authMethods.length > 1
      ? getAuthMethodFieldsForCredential(credentialJson, templateWithAuth)
      : Object.fromEntries(
          Object.entries(credentialTemplate).filter(
            ([key]) => key !== "authMethods"
          )
        );

  return {
    ...templateFields,
    ...credentialJson,
  };
}

export function createInitialValues(
  credential: Credential<any>,
  credentialFields: dictionaryType = credential.credential_json
): formType {
  const initialValues: formType = {
    name: credential.name || "",
  };

  for (const key in credentialFields) {
    // Initialize TypedFile fields as null, other fields as empty strings
    if (isTypedFileField(key)) {
      initialValues[key] = null as any; // TypedFile fields start as null
    } else {
      initialValues[key] = "";
    }
  }

  return initialValues;
}
