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
        `粘贴来自 ${provider.displayName} 的 [API Key](${
          provider.apiLink ?? ""
        }) 以访问模型。`
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
    <InputVertical title="上传 JSON 凭据文件" withLabel="apiKey">
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
  modelName: Yup.string().trim().required("请输入模型名称"),
  modelDim: Yup.number()
    .required("请输入模型维度")
    .test("positive-int", "必须是正整数", (value) => {
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
  modelNameSubDescription = "Glomi AI 将连接到你自托管端点上的这个模型。",
}: ModelSpecFieldsProps) {
  return (
    <>
      <TextField
        name="modelName"
        title="模型名称"
        placeholder="model-name"
        subDescription={modelNameSubDescription}
      />

      <Divider paddingParallel="fit" paddingPerpendicular="fit" />

      <TextField
        name="modelDim"
        title="模型维度"
        placeholder="例如：768"
        inputMode="numeric"
        subDescription="此模型生成嵌入向量的维度数。"
      />

      <TextField
        name="queryPrefix"
        title="查询前缀"
        suffix="可选"
        placeholder="例如：'query: '"
        subDescription="如果嵌入模型需要，此内容会在查询传给模型前添加到查询前。错误或缺失的前缀会降低嵌入质量。"
      />

      <TextField
        name="passagePrefix"
        title="段落前缀"
        suffix="可选"
        placeholder="例如：'passage: '"
        subDescription="如果嵌入模型需要，此内容会在索引文档分块传给模型前添加到分块前。错误或缺失的前缀会降低嵌入质量。"
      />

      <InputHorizontal
        title="归一化嵌入"
        description="对模型生成的嵌入向量进行归一化。除非模型文档另有说明，建议大多数模型开启。"
        withLabel="normalize"
      >
        <SwitchField name="normalize" />
      </InputHorizontal>
    </>
  );
}
