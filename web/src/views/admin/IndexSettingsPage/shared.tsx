"use client";

import { useField } from "formik";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import * as Yup from "yup";
import { markdown } from "@opal/utils";
import { Divider, InputFile } from "@opal/components";
import type { RichStr } from "@opal/types";
import { InputHorizontal, InputVertical } from "@opal/layouts";
import type {
  EmbeddingProvider,
  IndexSettingsTranslator,
} from "@/lib/searchSettings/types";
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
  optional?: boolean;
}

export function ApiKeyField({ provider, optional = false }: ApiKeyFieldProps) {
  const t = useTranslations("admin.indexSettings");

  return (
    <InputVertical
      title={t("fields.apiKey.title")}
      suffix={optional ? t("fields.optional.suffix") : undefined}
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
  const [, meta, helpers] = useField<string>("apiKey");
  return (
    <InputVertical
      title={t("fields.googleCredentials.title")}
      withLabel="apiKey"
    >
      <InputFile
        id="apiKey"
        name="apiKey"
        error={meta.touched && !!meta.error}
        setValue={(value) => {
          void helpers.setValue(value);
        }}
        onValueSet={() => {
          void helpers.setTouched(true);
        }}
        onBlur={() => {
          void helpers.setTouched(true);
        }}
        accept=".json"
      />
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
  readOnly?: boolean;
}

export function TextField({
  name,
  title,
  subDescription,
  suffix,
  placeholder,
  inputMode,
  readOnly = false,
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
        variant={readOnly ? "readOnly" : undefined}
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
  const { appName } = useSettings();

  return (
    <>
      <TextField
        name="modelName"
        title={t("fields.modelName.title")}
        placeholder={t("fields.modelName.placeholder")}
        subDescription={
          modelNameSubDescription ??
          t("fields.modelName.selfHostedDescription", { appName })
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
