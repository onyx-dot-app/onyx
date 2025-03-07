import * as Yup from "yup";

import { dictionaryType, formType } from "./types";
import {
  Credential,
  getDisplayNameForCredentialKey,
} from "@/lib/connectors/credentials";

export function createValidationSchema(json_values: Record<string, any>) {
  const schemaFields: Record<string, Yup.AnySchema> = {};

  for (const key in json_values) {
    if (!Object.prototype.hasOwnProperty.call(json_values, key)) {
      continue;
    }

    const displayName = getDisplayNameForCredentialKey(key);

    if (json_values[key] === null) {
      // Field is optional:
      schemaFields[key] = Yup.string()
        .trim()
        // Transform empty strings to null
        .transform((value) => (value === "" ? null : value))
        .nullable()
        .notRequired();
    } else {
      // Field is required:
      schemaFields[key] = Yup.string()
        .trim()
        // This ensures user cannot enter an empty string:
        .min(1, `${displayName} cannot be empty`)
        // The required message is shown if the field is missing
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
