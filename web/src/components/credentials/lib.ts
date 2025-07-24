import * as Yup from "yup";

import { dictionaryType, formType } from "./types";
import {
  Credential,
  getDisplayNameForCredentialKey,
  CredentialTemplateWithAuth,
} from "@/lib/connectors/credentials";

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
  const schemaFields: { [key: string]: Yup.StringSchema } = {};

  for (const key in json_values) {
    if (Object.prototype.hasOwnProperty.call(json_values, key)) {
      schemaFields[key] = Yup.string().optional();
    }
  }

  schemaFields["name"] = Yup.string().optional();
  return Yup.object().shape(schemaFields);
}

export function createInitialValues(credential: Credential<any>): formType {
  const initialValues: formType = {
    name: credential.name || "",
  };

  for (const key in credential.credential_json) {
    initialValues[key] = "";
  }

  return initialValues;
}
