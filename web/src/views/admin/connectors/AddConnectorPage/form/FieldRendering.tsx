import React, { FC, useEffect, useMemo } from "react";
import { useTranslations } from "next-intl";
import type {
  BooleanOption,
  TabOption,
  TextSubDescriptionKey,
} from "@/lib/connectors/types";
import SelectInput from "./inputs/SelectInput";
import NumberInput from "./inputs/NumberInput";
import { TextFormField, MultiSelectField } from "@/components/Field";
import ListInput from "./inputs/ListInput";
import StringPairListInput from "./inputs/StringPairListInput";
import FileInput from "./inputs/FileInput";
import type { ConfigurableSources } from "@/lib/connectors/types/source";
import type { Credential } from "@/lib/credentials/types";
import CollapsibleSection from "@/app/admin/agents/CollapsibleSection";
import { Tabs, Text as OpalText } from "@opal/components";
import { useField, useFormikContext } from "formik";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { Content, InputVertical, Label } from "@opal/layouts";
import { InputCheckboxField } from "@opal/form";
import type { IconFunctionComponent } from "@opal/types";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { getSourceDisplayName } from "@/lib/sources";
import Text from "@/refresh-components/texts/Text";

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
        <Text text03 secondaryBody>
          {t("tabs.empty.label")}
        </Text>
      ) : (
        <Tabs
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

interface CheckboxContentFieldProps {
  name: string;
  label: string;
  description: string | undefined;
  disabled: boolean;
}

/**
 * A checkbox option with the checkbox in the icon slot, left of the title.
 * The label around it hands a click on the title or description to the
 * checkbox.
 */
function CheckboxContentField({
  name,
  label,
  description,
  disabled,
}: CheckboxContentFieldProps) {
  // A stable component identity keeps React from remounting the checkbox.
  const checkboxIcon = useMemo<IconFunctionComponent>(() => {
    function CheckboxIcon() {
      return (
        <InputCheckboxField
          name={name}
          aria-label={label}
          disabled={disabled}
        />
      );
    }
    return CheckboxIcon;
  }, [name, label, disabled]);
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
        <FileInput
          name={field.name}
          isZip={field.type === "zip"}
          label={label}
          optional={field.optional}
          description={description}
        />
      ) : field.type === "list" ? (
        <ListInput name={field.name} label={label} description={description} />
      ) : field.type === "string_pair_list" ? (
        <StringPairListInput
          name={field.name}
          label={label}
          description={description}
          leftKey={field.leftKey}
          rightKey={field.rightKey}
          leftLabel={field.leftLabel}
          rightLabel={field.rightLabel}
          leftPlaceholder={field.leftPlaceholder}
          rightPlaceholder={field.rightPlaceholder}
        />
      ) : field.type === "select" ? (
        <SelectInput
          name={field.name}
          optional={field.optional}
          description={description}
          options={field.options || []}
          label={label}
        />
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
        <NumberInput
          label={label}
          optional={field.optional}
          description={description}
          name={field.name}
        />
      ) : field.type === "checkbox" && field.tabLabels ? (
        <CheckboxTabsField option={field} label={label} disabled={disabled} />
      ) : field.type === "checkbox" ? (
        <CheckboxContentField
          name={field.name}
          label={label}
          description={description}
          disabled={disabled}
        />
      ) : field.type === "text" ? (
        subDescriptionKey ? (
          <InputVertical
            withLabel={field.name}
            title={label}
            subDescription={t(`subDescriptions.${subDescriptionKey}`, {
              connectorName: getSourceDisplayName(connector) ?? connector,
            })}
            suffix={
              field.optional ? t("field.optionalSuffix.label") : undefined
            }
          >
            <InputTypeInField
              name={field.name}
              placeholder={field.placeholder}
              variant={disabled ? "disabled" : undefined}
            />
          </InputVertical>
        ) : field.isTextArea ? (
          <InputVertical
            withLabel={field.name}
            title={label}
            description={description}
            suffix={
              field.optional ? t("field.optionalSuffix.label") : undefined
            }
          >
            <InputTextAreaField
              name={field.name}
              placeholder={field.placeholder}
              variant={disabled ? "disabled" : undefined}
              rows={1}
            />
          </InputVertical>
        ) : (
          <TextFormField
            subtext={description}
            optional={field.optional}
            type={field.type}
            label={label}
            name={field.name}
            isTextArea={false}
            disabled={disabled}
            onChange={(e) => setFieldValue(field.name, e.target.value)}
          />
        )
      ) : field.type === "string_tab" ? (
        <GeneralLayouts.Section>
          <Text text03 secondaryBody>
            {description}
          </Text>
        </GeneralLayouts.Section>
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
