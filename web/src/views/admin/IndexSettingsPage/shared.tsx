"use client";

import { useState } from "react";
import { useField } from "formik";
import { useTranslations } from "next-intl";
import * as Yup from "yup";
import { markdown } from "@opal/utils";
import { Divider, Text } from "@opal/components";
import type { RichStr } from "@opal/types";
import { InputHorizontal, InputVertical } from "@opal/layouts";
import type { EmbeddingProvider } from "@/lib/indexing/types";
import SwitchField from "@/refresh-components/form/SwitchField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import PasswordInputTypeInField from "@/refresh-components/form/PasswordInputTypeInField";

/** Translator for the `admin.indexSettings` namespace, threaded into helpers
 *  that live outside a component and so cannot call the hook themselves. */
export type IndexSettingsTranslator = ReturnType<
  typeof useTranslations<"admin.indexSettings">
>;

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
  const t = useTranslations("admin.indexSettings");

  return (
    <InputVertical
      title={t("fields.apiKey.title")}
      withLabel="apiKey"
      subDescription={markdown(
        t("fields.apiKey.description", {
          link: provider.apiLink ?? "",
          provider: provider.displayName,
        })
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
  const t = useTranslations("admin.indexSettings");
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
    <InputVertical
      title={t("fields.googleCredentials.title")}
      withLabel="apiKey"
    >
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

export function modelSpecSchemaShape(t: IndexSettingsTranslator) {
  return {
    modelName: Yup.string().trim().required(t("validation.modelNameRequired")),
    modelDim: Yup.number()
      .required(t("validation.modelDimRequired"))
      .test("positive-int", t("validation.modelDimPositive"), (value) => {
        const parsed = Number(value);
        return Number.isInteger(parsed) && parsed > 0 && parsed <= 10000;
      }),
    queryPrefix: Yup.string().defined().default(""),
    passagePrefix: Yup.string().defined().default(""),
    normalize: Yup.boolean().defined().default(false),
  };
}

interface ModelSpecFieldsProps {
  modelNameSubDescription?: string;
}

export function ModelSpecFields({
  modelNameSubDescription,
}: ModelSpecFieldsProps) {
  const t = useTranslations("admin.indexSettings");

  return (
    <>
      <TextField
        name="modelName"
        title={t("fields.modelName.title")}
        placeholder={t("fields.modelName.placeholder")}
        subDescription={
          modelNameSubDescription ?? t("fields.modelName.selfHostedDescription")
        }
      />

      <Divider paddingParallel={0} paddingPerpendicular={0} />

      <TextField
        name="modelDim"
        title={t("fields.modelDim.title")}
        placeholder={t("fields.modelDim.placeholder")}
        inputMode="numeric"
        subDescription={t("fields.modelDim.description")}
      />

      <TextField
        name="queryPrefix"
        title={t("fields.queryPrefix.title")}
        suffix={t("fields.optional.suffix")}
        placeholder={t("fields.queryPrefix.placeholder")}
        subDescription={t("fields.queryPrefix.description")}
      />

      <TextField
        name="passagePrefix"
        title={t("fields.passagePrefix.title")}
        suffix={t("fields.optional.suffix")}
        placeholder={t("fields.passagePrefix.placeholder")}
        subDescription={t("fields.passagePrefix.description")}
      />

      <InputHorizontal
        title={t("fields.normalize.title")}
        description={t("fields.normalize.description")}
        withLabel="normalize"
      >
        <SwitchField name="normalize" />
      </InputHorizontal>
    </>
  );
}
