import React, { FC, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import type {
  BooleanOption,
  TabOption,
  TextSubDescriptionKey,
} from "@/lib/connectors/types";
import { MultiSelectField } from "@/components/Field";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";
import CollapsibleSection from "@/app/admin/agents/CollapsibleSection";
import {
  InputKeyValue,
  InputNumber,
  Tabs,
  Text as OpalText,
} from "@opal/components";
import { useField, useFormikContext } from "formik";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Content, InputHorizontal, InputVertical, Label } from "@opal/layouts";
import { InputCheckboxField, InputSingleSelectField } from "@opal/form";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import SwitchField from "@/refresh-components/form/SwitchField";
import TextListField from "@/refresh-components/form/TextListField";
import FileDropzoneField from "@/refresh-components/form/FileDropzoneField";
import { FormikField } from "@/refresh-components/form/FormikField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { getSourceDisplayName } from "@/lib/sources";
import { markdown } from "@opal/utils";

// Define a general type for form values
type FormValues = Record<string, any>;

interface TabsFieldProps {
  tabField: TabOption;
  values: any;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
}

const TabsField: FC<TabsFieldProps> = ({
  tabField,
  values,
  connector,
  currentCredential,
}) => {
  const t = useTranslations("admin.connectorsList");
  const { setFieldTouched, setFieldValue } = useFormikContext<FormValues>();

  const resolvedLabel =
    typeof tabField.label === "function"
      ? tabField.label(currentCredential)
      : tabField.label;
  const resolvedDescription =
    typeof tabField.description === "function"
      ? tabField.description(currentCredential)
      : tabField.description;

  return (
    <GeneralLayouts.Section gap={2} alignItems="start">
      {tabField.label && (
        <Content
          title={resolvedLabel ?? ""}
          description={resolvedDescription}
          sizePreset="main-content"
          variant="section"
        />
      )}

      {/* Ensure there's at least one tab before rendering */}
      {tabField.tabs.length === 0 ? (
        <OpalText font="secondary-body" color="text-03">
          {t("tabs.empty.label")}
        </OpalText>
      ) : (
        <Tabs
          // Space between the tab strip and the fields of the open tab.
          gap={4}
          value={
            values[tabField.name] ??
            tabField.defaultTab ??
            tabField.tabs[0]?.value
          }
          onValueChange={(newTab) => {
            setFieldValue(tabField.name, newTab);
            tabField.tabs
              .find((tab) => tab.value === newTab)
              ?.fields.forEach((field) => setFieldTouched(field.name, true));
            // Clear values from other tabs but preserve defaults
            tabField.tabs.forEach((tab) => {
              if (tab.value !== newTab) {
                tab.fields.forEach((field) => {
                  // Only clear if not default value
                  if (!Object.is(values[field.name], field.default)) {
                    setFieldValue(field.name, field.default);
                  }
                });
              }
            });
          }}
        >
          <Tabs.List>
            {tabField.tabs.map((tab) => (
              <Tabs.Trigger key={tab.value} value={tab.value}>
                {tab.label}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          {tabField.tabs.map((tab) => (
            <Tabs.Content key={tab.value} value={tab.value}>
              <GeneralLayouts.Section gap={3} alignItems="start">
                {tab.fields.map((subField) => {
                  // Check visibility condition first
                  if (
                    subField.visibleCondition &&
                    !subField.visibleCondition(values, currentCredential)
                  ) {
                    return null;
                  }

                  return (
                    <RenderField
                      key={subField.name}
                      field={subField}
                      values={values}
                      connector={connector}
                      currentCredential={currentCredential}
                    />
                  );
                })}
              </GeneralLayouts.Section>
            </Tabs.Content>
          ))}
        </Tabs>
      )}
    </GeneralLayouts.Section>
  );
};

interface CheckboxTabsFieldProps {
  option: BooleanOption & Required<Pick<BooleanOption, "tabLabels">>;
  label: string;
  disabled: boolean;
}

/**
 * A checkbox option shown as two tabs. The tab labels name both choices, so
 * the label only names the tab strip for assistive technology.
 */
function CheckboxTabsField({
  option,
  label,
  disabled,
}: CheckboxTabsFieldProps) {
  const t = useTranslations("admin.connectorsList.checkboxTabs");
  const [{ value }, { error, touched }, { setValue, setTouched }] = useField<
    boolean | undefined
  >(option.name);
  // The tab strip carries strings; the form value stays a boolean.
  return (
    <GeneralLayouts.Section gap={1} alignItems="start">
      <Tabs
        value={String(value ?? option.default ?? false)}
        onValueChange={(next) => {
          setTouched(true, false);
          setValue(next === "true");
        }}
      >
        <Tabs.List aria-label={label}>
          <Tabs.Trigger value="true" disabled={disabled}>
            {t(option.tabLabels.true)}
          </Tabs.Trigger>
          <Tabs.Trigger value="false" disabled={disabled}>
            {t(option.tabLabels.false)}
          </Tabs.Trigger>
        </Tabs.List>
      </Tabs>
      {touched && error && (
        <OpalText font="secondary-body" color="status-error-05" role="alert">
          {error}
        </OpalText>
      )}
    </GeneralLayouts.Section>
  );
}

interface CheckboxFieldProps {
  name: string;
  label: string | RichStr;
  description: string | RichStr | undefined;
  disabled: boolean;
}

/**
 * A boolean option with the checkbox in the icon slot, left of the title.
 * The label around it hands a click on the title or description to the
 * checkbox.
 */
function CheckboxField({
  name,
  label,
  description,
  disabled,
}: CheckboxFieldProps) {
  // A stable component identity keeps React from remounting the checkbox.
  const ariaLabel: string = typeof label === "string" ? label : label.raw;
  const checkboxIcon = useMemo<IconFunctionComponent>(() => {
    function CheckboxIcon() {
      return (
        <InputCheckboxField
          name={name}
          aria-label={ariaLabel}
          disabled={disabled}
        />
      );
    }
    return CheckboxIcon;
  }, [name, ariaLabel, disabled]);

  return (
    <Label disabled={disabled}>
      <Content
        icon={checkboxIcon}
        title={label}
        description={description}
        sizePreset="main-ui"
        variant="section"
      />
    </Label>
  );
}

interface ToggleFieldProps {
  name: string;
  label: string | RichStr;
  description: string | RichStr | undefined;
  disabled: boolean;
}

/** A boolean option as a switch, with its title and description on the left. */
function ToggleField({ name, label, description, disabled }: ToggleFieldProps) {
  return (
    <InputHorizontal
      withLabel
      disabled={disabled}
      title={label}
      description={description}
    >
      <SwitchField name={name} disabled={disabled} />
    </InputHorizontal>
  );
}

interface RenderFieldProps {
  field: any;
  values: any;
  connector: ConfigurableSources;
  currentCredential: Credential<any> | null;
}

export const RenderField: FC<RenderFieldProps> = ({
  field,
  values,
  connector,
  currentCredential,
}) => {
  const t = useTranslations("admin.connectorsList");
  const { setFieldValue } = useFormikContext<FormValues>(); // Get Formik's context functions

  const label =
    typeof field.label === "function"
      ? field.label(currentCredential)
      : field.label;
  const description =
    typeof field.description === "function"
      ? field.description(currentCredential)
      : field.description;
  const disabled =
    typeof field.disabled === "function"
      ? field.disabled(currentCredential)
      : (field.disabled ?? false);
  const initialValue =
    typeof field.initial === "function"
      ? field.initial(currentCredential)
      : (field.initial ?? "");
  const subDescriptionKey: TextSubDescriptionKey | undefined =
    field.type === "text" ? field.subDescription : undefined;
  // Config descriptions carry inline markdown, such as links and `code`.
  const richDescription: RichStr | undefined =
    typeof description === "string" && description
      ? markdown(description)
      : undefined;
  const optionalSuffix: string | undefined = field.optional
    ? t("field.optionalSuffix.label")
    : undefined;

  // Prepopulate the field with initialValue. A field that the credential
  // disables takes the credential's value, also over a value entered before
  // the credential was selected.
  useEffect(() => {
    const field_value = values[field.name];
    if (
      initialValue &&
      (field_value === undefined || (disabled && field_value !== initialValue))
    ) {
      setFieldValue(field.name, initialValue);
    }
  }, [field.name, initialValue, disabled, setFieldValue, values]);

  if (field.type === "tab") {
    return (
      <TabsField
        tabField={field}
        values={values}
        connector={connector}
        currentCredential={currentCredential}
      />
    );
  }

  const fieldContent = (
    <>
      {field.type === "zip" || field.type === "file" ? (
        // The field name ties the label to the file input's id and shows the
        // field's Formik error under it.
        <InputVertical
          withLabel={field.name}
          disabled={disabled}
          title={label}
          subDescription={richDescription}
          suffix={optionalSuffix}
        >
          <FileDropzoneField
            name={field.name}
            isZip={field.type === "zip"}
            aria-label={label}
            disabled={disabled}
          />
        </InputVertical>
      ) : field.type === "list" ? (
        <InputVertical
          disabled={disabled}
          title={label}
          subDescription={richDescription}
          suffix={optionalSuffix}
        >
          <TextListField
            name={field.name}
            placeholder={t("listInput.placeholder", {
              label: label.toLowerCase(),
            })}
            disabled={disabled}
          />
        </InputVertical>
      ) : field.type === "string_pair_list" ? (
        <InputVertical
          disabled={disabled}
          title={label}
          subDescription={richDescription}
          suffix={optionalSuffix}
        >
          {/* InputKeyValue edits { key, value } rows; the config names the
            keys each row saves under, such as { source, target }. */}
          <FormikField<Record<string, string>[] | undefined>
            name={field.name}
            render={(formikField, helper) => (
              <InputKeyValue
                keyTitle={field.leftLabel}
                valueTitle={field.rightLabel}
                keyPlaceholder={field.leftPlaceholder}
                valuePlaceholder={field.rightPlaceholder}
                items={(formikField.value ?? []).map((row) => ({
                  key: row[field.leftKey] ?? "",
                  value: row[field.rightKey] ?? "",
                }))}
                onChange={(items) =>
                  void helper.setValue(
                    items.map((item) => ({
                      [field.leftKey]: item.key,
                      [field.rightKey]: item.value,
                    }))
                  )
                }
              />
            )}
          />
        </InputVertical>
      ) : field.type === "select" ? (
        // The field name ties the label to the select's id and shows the
        // field's Formik error under it.
        <InputVertical
          withLabel={field.name}
          disabled={disabled}
          title={label}
          subDescription={richDescription}
          suffix={optionalSuffix}
        >
          <InputSingleSelectField
            name={field.name}
            id={field.name}
            placeholder={t("selectInput.emptyOption.label")}
            disabled={disabled}
            options={[
              {
                options: (field.options ?? []).map(
                  (option: { name: string }) => ({
                    value: option.name,
                    title: option.name,
                  })
                ),
              },
            ]}
          />
        </InputVertical>
      ) : field.type === "multiselect" ? (
        <MultiSelectField
          name={field.name}
          label={label}
          subtext={description}
          options={
            field.options?.map((option: { value: string; name: string }) => ({
              value: option.value,
              label: option.name,
            })) || []
          }
          selectedInitially={values[field.name] || field.default || []}
          onChange={(selected) => setFieldValue(field.name, selected)}
        />
      ) : field.type === "number" ? (
        <InputVertical
          withLabel={field.name}
          disabled={disabled}
          title={label}
          subDescription={richDescription}
          suffix={optionalSuffix}
        >
          <FormikField<number | undefined>
            name={field.name}
            render={(formikField, helper, _meta, status) => (
              <InputNumber
                id={field.name}
                value={formikField.value ?? null}
                onChange={(value) => {
                  // InputNumber has no blur callback, so touch on change to
                  // show the field's validation error.
                  void helper.setTouched(true, false);
                  void helper.setValue(value ?? undefined);
                }}
                // Some sources take -1 for "no limit", such as a recursion
                // depth.
                min={-1}
                variant={status === "error" ? "error" : "primary"}
                disabled={disabled}
              />
            )}
          />
        </InputVertical>
      ) : field.type === "checkbox" && field.tabLabels ? (
        <CheckboxTabsField option={field} label={label} disabled={disabled} />
      ) : field.type === "checkbox" && field.asCheckbox ? (
        <CheckboxField
          name={field.name}
          label={label}
          description={richDescription}
          disabled={disabled}
        />
      ) : field.type === "checkbox" ? (
        <ToggleField
          name={field.name}
          label={label}
          description={richDescription}
          disabled={disabled}
        />
      ) : field.type === "text" ? (
        // The field name ties the label to the input's id and shows the
        // field's Formik error under it.
        <InputVertical
          withLabel={field.name}
          title={label}
          subDescription={
            subDescriptionKey
              ? t(`subDescriptions.${subDescriptionKey}`, {
                  connectorName: getSourceDisplayName(connector) ?? connector,
                })
              : richDescription
          }
          suffix={optionalSuffix}
        >
          {field.isTextArea ? (
            <InputTextAreaField
              name={field.name}
              placeholder={field.placeholder}
              variant={disabled ? "disabled" : undefined}
              rows={1}
            />
          ) : (
            <InputTypeInField
              name={field.name}
              placeholder={field.placeholder}
              variant={disabled ? "disabled" : undefined}
            />
          )}
        </InputVertical>
      ) : field.type === "string_tab" ? (
        <OpalText font="secondary-body" color="text-03">
          {richDescription ?? ""}
        </OpalText>
      ) : (
        <>
          {/* oxlint-disable-next-line i18n/no-raw-jsx-text -- developer diagnostic, not copy */}
          INVALID FIELD TYPE
        </>
      )}
    </>
  );

  if (field.wrapInCollapsible) {
    return (
      <CollapsibleSection prompt={label} key={field.name}>
        {fieldContent}
      </CollapsibleSection>
    );
  }

  return (
    <GeneralLayouts.Section alignItems="start">
      {fieldContent}
    </GeneralLayouts.Section>
  );
};
