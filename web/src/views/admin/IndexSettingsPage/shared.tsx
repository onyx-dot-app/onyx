"use client";

import { useState } from "react";
import { useField } from "formik";
import * as Yup from "yup";
import { markdown } from "@opal/utils";
import { Divider, Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import { InputHorizontal, InputVertical } from "@opal/layouts";
import type { EmbeddingProvider } from "@/lib/indexing/interfaces";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";

// ---------------------------------------------------------------------------
// Formik-aware field components
//
// Every field in this file expects to live inside a <Formik> context. The
// matching Yup schema field name is passed via `name`; `withLabel={name}`
// on the Opal `InputVertical` / `InputHorizontal` wires the `<label htmlFor>`
// AND the inline error-text rendered by `FormikInputError`.
// ---------------------------------------------------------------------------

interface ApiKeyFieldProps {
  provider: EmbeddingProvider;
}

export function ApiKeyField({ provider }: ApiKeyFieldProps) {
  return (
    <InputVertical
      title="API Key"
      withLabel="apiKey"
      subDescription={markdown(
        `Paste your [API key](${provider.apiLink ?? ""}) from ${
          provider.displayName
        } to access your models.`
      )}
    >
      <PasswordInputTypeInField name="apiKey" />
    </InputVertical>
  );
}

interface ApiUrlFieldProps {
  title: string;
  placeholder: string;
  subDescription?: string;
}

export function ApiUrlField({
  title,
  placeholder,
  subDescription,
}: ApiUrlFieldProps) {
  return (
    <InputVertical
      title={title}
      subDescription={subDescription}
      withLabel="apiUrl"
    >
      <InputTypeInField name="apiUrl" placeholder={placeholder} />
    </InputVertical>
  );
}

export function GoogleCredentialsField() {
  const [, , helpers] = useField<string>("apiKey");
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
    <InputVertical title="Upload JSON credentials file" withLabel="apiKey">
      <input
        id="apiKey"
        type="file"
        accept=".json"
        onChange={handleFileUpload}
      />
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
  return (
    <InputVertical
      title={title}
      subDescription={subDescription}
      suffix={suffix}
      withLabel={name}
    >
      <InputTypeInField
        name={name}
        placeholder={placeholder}
        inputMode={inputMode}
      />
    </InputVertical>
  );
}

// ---------------------------------------------------------------------------
// Model spec fields — shared between LiteLLMProviderModal and
// CustomSelfHostedModal. Both collect the same 5 fields; only the modelName
// subDescription differs.
// ---------------------------------------------------------------------------

export const modelSpecSchemaShape = {
  modelName: Yup.string().trim().required("Model name is required"),
  modelDim: Yup.number()
    .required("Model dimension is required")
    .test("positive-int", "Must be a positive integer", (value) => {
      const parsed = Number(value);
      return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000;
    }),
  queryPrefix: Yup.string().defined().default(""),
  passagePrefix: Yup.string().defined().default(""),
  normalize: Yup.boolean().defined().default(false),
};

interface ModelSpecFieldsProps {
  modelNameSubDescription?: string;
}

export function ModelSpecFields({
  modelNameSubDescription = "Onyx will connect to this model on your self-hosted endpoint.",
}: ModelSpecFieldsProps) {
  return (
    <>
      <TextField
        name="modelName"
        title="Model Name"
        placeholder="model-name"
        subDescription={modelNameSubDescription}
      />

      <Divider paddingParallel="fit" paddingPerpendicular="fit" />

      <TextField
        name="modelDim"
        title="Model Dimension"
        placeholder="e.g., 768"
        inputMode="numeric"
        subDescription="Number of dimensions in the embeddings generated by this model."
      />

      <TextField
        name="queryPrefix"
        title="Query Prefix"
        suffix="optional"
        placeholder="e.g., 'query: '"
        subDescription="This is prepended to search queries before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
      />

      <TextField
        name="passagePrefix"
        title="Passage Prefix"
        suffix="optional"
        placeholder="e.g., 'passage: '"
        subDescription="This is prepended to indexed document chunks before passing to the model, if required by your embedding model. Incorrect or missing prefixes will degrade embedding quality."
      />

      <InputHorizontal
        title="Normalize Embeddings"
        description="Normalize the embeddings generated by the model. Recommended for most models unless your embedding model documentation specifies otherwise."
        withLabel="normalize"
      >
        <SwitchField name="normalize" />
      </InputHorizontal>
    </>
  );
}
