"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  InputSingleUpload,
  InputPasswordTypeIn,
  InputSwitch,
  InputTypeIn,
  MessageCard,
  Tabs,
} from "@opal/components";
import {
  Content,
  InputErrorText,
  InputHorizontal,
  InputVertical,
  Label,
  Section,
} from "@opal/layouts";
import { InputCheckboxField } from "@opal/form";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { markdown } from "@opal/utils";
import { getIn, useField, useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { FILE_TYPE_DEFINITIONS, TypedFile } from "@/lib/connectors/fileTypes";
import { createTypedFile } from "@/lib/connectors/utils";
import { FormikField } from "@/refresh-components/form/FormikField";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import {
  fileToBase64,
  getCredentialFileType,
  getCredentialSpec,
  methodFields,
} from "@/lib/credentials/utils";
import type {
  CredentialFieldValues,
  CredentialSpec,
  CredentialSpecField,
} from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";

/**
 * How a file field holds its file: a `TypedFile`, uploaded on its own when
 * the account is saved, or the file's base64 text, sent with the account's
 * other values (a new account typed into a connector form).
 */
export type CredentialFileValues = "typedFile" | "base64";

interface CredentialFieldProps {
  source: ValidSources;
  fieldKey: string;
  field: CredentialSpecField;
  /** The Formik path the field lives under, e.g. `new_account`. */
  namePrefix?: string;
  fileValues?: CredentialFileValues;
}

/**
 * A checkbox bound to one Formik field, shaped as a `Content` icon so it sits
 * where an icon would. It depends only on the field name, so it keeps its
 * identity across renders and React never remounts the checkbox (which would
 * drop its focus on every toggle). The icon's class and size are not passed
 * on: the checkbox keeps its own colours and is already the icon's 1rem.
 */
function useCheckboxIcon(name: string, label: string): IconFunctionComponent {
  return useMemo(() => {
    // The label names the visible checkbox; the wrapping <label> only names
    // its hidden native input.
    function CheckboxIcon() {
      return <InputCheckboxField name={name} aria-label={label} />;
    }
    return CheckboxIcon;
  }, [name, label]);
}

/** One field of a credential spec, drawn with the Opal input for its kind. */
function CredentialField({
  source,
  fieldKey,
  field,
  namePrefix,
  fileValues = "typedFile",
}: CredentialFieldProps) {
  const t = useTranslations("admin");
  const copy = useCredentialFieldCopy(source)(fieldKey);
  const label = copy.title;
  // The Formik path; the spec key stays the copy and test id.
  const name: string = namePrefix ? `${namePrefix}.${fieldKey}` : fieldKey;
  const checkboxIcon = useCheckboxIcon(name, label);

  if (field.kind === "file") {
    return (
      <CredentialFileField
        name={name}
        fieldKey={fieldKey}
        label={label}
        description={copy.description}
        values={fileValues}
      />
    );
  }

  // The checkbox stands in for the icon, left of the title. The label around
  // it hands a click on the title or description to the checkbox.
  if (field.kind === "checkbox") {
    return (
      <Label>
        <Content
          icon={checkboxIcon}
          title={label}
          description={copy.description}
          sizePreset="main-ui"
          variant="section"
        />
      </Label>
    );
  }

  if (field.kind === "toggle") {
    return (
      <InputHorizontal withLabel title={label}>
        <FormikField<boolean>
          name={name}
          render={(formikField, helper) => (
            <InputSwitch
              checked={!!formikField.value}
              onCheckedChange={(checked) => helper.setValue(checked)}
            />
          )}
        />
      </InputHorizontal>
    );
  }

  const placeholder =
    field.kind === "email"
      ? t("credentials.create.emailField.placeholder")
      : undefined;
  // The account email pairs with an API token, so it says which account,
  // under the input.
  const subDescription =
    field.displayName === "accountEmail"
      ? t("credentials.create.accountEmailField.subDescription")
      : field.displayName === "apiToken"
        ? t("credentials.create.apiTokenField.subDescription", {
            source: getCredentialSpec(source)?.brandName ?? source,
          })
        : undefined;

  return (
    // The field name ties the label to the input's id and shows the field's
    // Formik error under it.
    <InputVertical
      withLabel={name}
      title={label}
      subDescription={subDescription}
    >
      <FormikField<string>
        name={name}
        render={(formikField, _helper, _meta, status) =>
          field.kind === "secret" ? (
            <InputPasswordTypeIn
              {...formikField}
              id={name}
              data-testid={fieldKey}
              value={formikField.value ?? ""}
              placeholder={placeholder}
              error={status === "error"}
            />
          ) : (
            <InputTypeIn
              {...formikField}
              id={name}
              data-testid={fieldKey}
              value={formikField.value ?? ""}
              placeholder={placeholder}
              variant={status === "error" ? "error" : "primary"}
            />
          )
        }
      />
    </InputVertical>
  );
}

interface CredentialFileFieldProps {
  /** The Formik path. */
  name: string;
  /** The spec key: it picks the file's type and names it to the server. */
  fieldKey: string;
  label: string | RichStr;
  /**
   * The field's hint. A plain string is read as markdown, so `.pfx` in
   * backticks shows as code.
   */
  description?: string | RichStr;
  /** How the field holds the file. @default "typedFile" */
  values?: CredentialFileValues;
}

/**
 * A key file, such as a .pfx certificate, checked against its type's size
 * and extensions when picked. The field holds it as a `TypedFile`, or as its
 * base64 text with `values="base64"`; either way the bytes stay intact.
 */
export function CredentialFileField({
  name,
  fieldKey,
  label,
  description,
  values = "typedFile",
}: CredentialFileFieldProps) {
  const t = useTranslations("common.field");
  const [field, , helpers] = useField<TypedFile | string | null>(name);
  const [fileError, setFileError] = useState<string | null>(null);
  // As base64 text the field cannot name its file, so the picked file is
  // kept to show; a cleared or reset field drops it.
  const [pickedFile, setPickedFile] = useState<File | null>(null);
  const hasValue: boolean = field.value !== null && field.value !== "";
  useEffect(() => {
    if (!hasValue) setPickedFile(null);
  }, [hasValue]);
  const shownFile: File | null =
    field.value instanceof TypedFile
      ? field.value.file
      : hasValue
        ? pickedFile
        : null;
  const fileType = getCredentialFileType(fieldKey);
  const definition = fileType ? FILE_TYPE_DEFINITIONS[fileType] : null;

  // Each pick is numbered; a read that a later pick or a clear overtook is
  // dropped, so it cannot bring back an older file.
  const latestPickRef = useRef<number>(0);

  async function takeFile(file: File | null) {
    const pick = ++latestPickRef.current;
    const isLatest = () => pick === latestPickRef.current;
    setFileError(null);
    // Until the new file is checked and read, the field holds no file, so
    // nothing can send the previous one under the new name.
    setPickedFile(null);
    void helpers.setValue(null);
    if (!file) return;
    if (!fileType) {
      setFileError(t("fileValidation.noTypeDefinition", { name: fieldKey }));
      return;
    }
    const typedFile = createTypedFile(file, fieldKey, fileType);
    const { isValid, errors } = await typedFile.validate();
    if (!isLatest()) return;
    if (!isValid) {
      setFileError(errors.join(", ") || t("fileValidation.unknownError"));
      return;
    }
    let value: TypedFile | string;
    try {
      value = values === "base64" ? await fileToBase64(file) : typedFile;
    } catch {
      if (isLatest()) setFileError(t("fileValidation.selectionError"));
      return;
    }
    if (!isLatest()) return;
    setPickedFile(file);
    void helpers.setValue(value);
    void helpers.setTouched(true, false);
  }

  return (
    <InputVertical
      withLabel={name}
      title={label}
      subDescription={
        typeof description === "string" ? markdown(description) : description
      }
    >
      <InputSingleUpload
        mode="file"
        id={name}
        name={name}
        data-testid={fieldKey}
        accept={definition?.validation?.allowedExtensions?.join(",")}
        value={shownFile}
        onFileChange={(file) => void takeFile(file)}
        variant={fileError ? "error" : "primary"}
      />
      {fileError && <InputErrorText type="error">{fileError}</InputErrorText>}
    </InputVertical>
  );
}

interface CredentialFieldsRendererProps {
  source: ValidSources;
  spec: CredentialSpec;
  authMethod?: string;
  setAuthMethod?: (method: string) => void;
  /**
   * The Formik path the credential's values live under, e.g. `new_account`
   * inside a larger form. Unset, they are the form's own values.
   */
  namePrefix?: string;
  /** Field keys this renderer leaves out, e.g. ones drawn elsewhere. */
  exclude?: ReadonlySet<string>;
  /** How file fields hold their file. @default "typedFile" */
  fileValues?: CredentialFileValues;
}

export function CredentialFieldsRenderer({
  source,
  spec,
  authMethod,
  setAuthMethod,
  namePrefix,
  exclude,
  fileValues,
}: CredentialFieldsRendererProps) {
  const t = useTranslations("admin");
  const { values, setValues, setFieldValue } =
    useFormikContext<CredentialFieldValues>();
  const methods = spec.methods;
  const credentialValues: CredentialFieldValues = namePrefix
    ? (getIn(values, namePrefix) ?? {})
    : values;

  // Switching auth method drops the fields only the other methods use.
  function handleAuthMethodChange(newMethod: string) {
    const kept = new Set(
      methods?.find((method) => method.value === newMethod)?.fields
    );
    const cleaned: CredentialFieldValues = {
      ...credentialValues,
      authentication_method: newMethod,
    };
    Object.keys(spec.fields).forEach((fieldKey) => {
      if (!kept.has(fieldKey)) delete cleaned[fieldKey];
    });
    if (namePrefix) {
      setFieldValue(namePrefix, cleaned);
    } else {
      setValues(cleaned);
    }
    setAuthMethod?.(newMethod);
  }

  if (methods && methods.length > 1) {
    return (
      <Tabs
        gap={4}
        value={authMethod || methods[0]?.value || ""}
        onValueChange={handleAuthMethodChange}
      >
        <Tabs.List>
          {methods.map((method) => (
            <Tabs.Trigger key={method.value} value={method.value}>
              {t(`credentials.methods.labels.${method.label}`)}
            </Tabs.Trigger>
          ))}
        </Tabs.List>

        {methods.map((method) => (
          <Tabs.Content key={method.value} value={method.value}>
            <Section alignItems="stretch" gap={4}>
              {/* A method with nothing to fill in explains itself instead. */}
              {method.fields.length === 0 && method.description && (
                <MessageCard
                  variant="info"
                  title={t(
                    `credentials.methods.descriptions.${method.description}`
                  )}
                />
              )}
              {methodFields(spec, method)
                .filter(([key]) => !exclude?.has(key))
                .map(([key, field]) => (
                  <CredentialField
                    key={key}
                    source={source}
                    fieldKey={key}
                    field={field}
                    namePrefix={namePrefix}
                    fileValues={fileValues}
                  />
                ))}
            </Section>
          </Tabs.Content>
        ))}
      </Tabs>
    );
  }

  return (
    <>
      {Object.entries(spec.fields)
        .filter(([key]) => !exclude?.has(key))
        .map(([key, field]) => (
          <CredentialField
            key={key}
            source={source}
            fieldKey={key}
            field={field}
            namePrefix={namePrefix}
            fileValues={fileValues}
          />
        ))}
    </>
  );
}
