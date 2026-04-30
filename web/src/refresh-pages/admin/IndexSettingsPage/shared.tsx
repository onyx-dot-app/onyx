"use client";

import { useState } from "react";
import { useField } from "formik";
import { markdown } from "@opal/utils";
import { Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import { InputHorizontal, InputVertical } from "@opal/layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";
import Switch from "@/refresh-components/inputs/Switch";
import type { EmbeddingProvider } from "@/lib/indexing/interfaces";

// ---------------------------------------------------------------------------
// Formik-aware field components
//
// Every field in this file expects to live inside a <Formik> context. The
// matching Yup schema field name is passed via `name`; `withLabel={name}`
// on the Opal `InputVertical` / `InputHorizontal` wires the `<label htmlFor>`
// AND the inline error-text rendered by `FormikInputError`.
// ---------------------------------------------------------------------------

interface ApiKeyFieldProps {
  name: string;
  provider: EmbeddingProvider;
}

export function ApiKeyField({ name, provider }: ApiKeyFieldProps) {
  const [field] = useField<string>(name);
  return (
    <InputVertical
      title="API Key"
      withLabel={name}
      subDescription={markdown(
        `Paste your [API key](${provider.apiLink ?? ""}) from ${
          provider.displayName
        } to access your models.`
      )}
    >
      <PasswordInputTypeIn id={name} {...field} />
    </InputVertical>
  );
}

interface ApiUrlFieldProps {
  name: string;
  title: string;
  placeholder: string;
  subDescription?: string;
}

export function ApiUrlField({
  name,
  title,
  placeholder,
  subDescription,
}: ApiUrlFieldProps) {
  const [field] = useField<string>(name);
  return (
    <InputVertical
      title={title}
      subDescription={subDescription}
      withLabel={name}
    >
      <InputTypeIn id={name} placeholder={placeholder} {...field} />
    </InputVertical>
  );
}

interface GoogleCredentialsFieldProps {
  name: string;
  isEditing?: boolean;
}

export function GoogleCredentialsField({
  name,
  isEditing,
}: GoogleCredentialsFieldProps) {
  const [, , helpers] = useField<string>(name);
  const [fileName, setFileName] = useState("");

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    setFileName("");
    if (!file) {
      void helpers.setValue("");
      void helpers.setTouched(true);
      return;
    }
    setFileName(file.name);
    try {
      const content = JSON.parse(await file.text());
      void helpers.setValue(JSON.stringify(content));
    } catch {
      void helpers.setValue("");
    }
    void helpers.setTouched(true);
  };

  return (
    <InputVertical
      title="Upload JSON credentials file"
      withLabel={name}
      subDescription={
        isEditing
          ? "Leave blank to keep the existing credentials, or upload a new file to replace them."
          : undefined
      }
    >
      <input id={name} type="file" accept=".json" onChange={handleFileUpload} />
      {fileName && (
        <Text font="secondary-body" color="text-03">
          {fileName}
        </Text>
      )}
    </InputVertical>
  );
}

interface TextFieldProps {
  name: string;
  title: string | RichStr;
  subDescription?: string | RichStr;
  suffix?: string;
  placeholder?: string;
  inputMode?: React.HTMLAttributes<HTMLInputElement>["inputMode"];
}

export function TextField({
  name,
  title,
  subDescription,
  suffix,
  placeholder,
  inputMode,
}: TextFieldProps) {
  const [field] = useField<string>(name);
  return (
    <InputVertical
      title={title}
      subDescription={subDescription}
      suffix={suffix}
      withLabel={name}
    >
      <InputTypeIn
        id={name}
        placeholder={placeholder}
        inputMode={inputMode}
        {...field}
      />
    </InputVertical>
  );
}

interface BoolFieldProps {
  name: string;
  title: string | RichStr;
  description?: string | RichStr;
}

export function BoolField({ name, title, description }: BoolFieldProps) {
  const [field, , helpers] = useField<boolean>(name);
  return (
    <InputHorizontal title={title} description={description} withLabel>
      <Switch
        checked={field.value}
        onCheckedChange={(checked) => void helpers.setValue(checked)}
      />
    </InputHorizontal>
  );
}
