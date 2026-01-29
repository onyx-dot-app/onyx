import React, { FC, useEffect } from "react";
import { TabOption } from "@/lib/connectors/connectors";
import SelectInput from "./ConnectorInput/SelectInput";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField, MultiSelectField } from "@/components/Field";
import ListInput from "./ConnectorInput/ListInput";
import FileInput from "./ConnectorInput/FileInput";
import { ConfigurableSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import CollapsibleSection from "@/app/admin/assistants/CollapsibleSection";
import Tabs from "@/refresh-components/Tabs";
import { useFormikContext } from "formik";
import * as GeneralLayouts from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import CheckboxField from "@/refresh-components/form/LabeledCheckboxField";
import InputTextAreaField from "@/refresh-components/form/InputTextAreaField";
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
  const { setFieldValue } = useFormikContext<FormValues>();

  const resolvedLabel =
    typeof tabField.label === "function"
      ? tabField.label(currentCredential)
      : tabField.label;
  const resolvedDescription =
    typeof tabField.description === "function"
      ? tabField.description(currentCredential)
      : tabField.description;

  return (
    <GeneralLayouts.Section gap={0.5} alignItems="start">
      {tabField.label && (
        <InputLayouts.Title
          title={resolvedLabel ?? ""}
          description={resolvedDescription}
        />
      )}

      {/* Ensure there's at least one tab before rendering */}
      {tabField.tabs.length === 0 ? (
        <Text text03 secondaryBody>
          No tabs to display.
        </Text>
      ) : (
        <Tabs
          defaultValue={tabField.defaultTab || tabField.tabs[0]?.value}
          onValueChange={(newTab) => {
            // Clear values from other tabs but preserve defaults
            tabField.tabs.forEach((tab) => {
              if (tab.value !== newTab) {
                tab.fields.forEach((field) => {
                  // Only clear if not default value
                  if (values[field.name] !== field.default) {
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
              <GeneralLayouts.Section gap={0.75} alignItems="start">
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
      : field.disabled ?? false;
  const initialValue =
    typeof field.initial === "function"
      ? field.initial(currentCredential)
      : field.initial ?? "";

  // if initialValue exists, prepopulate the field with it
  useEffect(() => {
    const field_value = values[field.name];
    if (initialValue && field_value === undefined) {
      setFieldValue(field.name, initialValue);
    }
  }, [field.name, initialValue, setFieldValue, values]);

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
      ) : field.type === "checkbox" ? (
        <GeneralLayouts.Section
          flexDirection="row"
          justifyContent="start"
          alignItems="start"
          gap={0.5}
        >
          <CheckboxField
            name={field.name}
            label={label}
            sublabel={description}
            disabled={disabled}
            size="lg"
            onChange={(checked) => setFieldValue(field.name, checked)}
          />
        </GeneralLayouts.Section>
      ) : field.type === "text" ? (
        field.isTextArea ? (
          <InputLayouts.Vertical
            name={field.name}
            title={label}
            description={description}
            optional={field.optional}
          >
            <InputTextAreaField
              name={field.name}
              placeholder={field.placeholder}
              variant={disabled ? "disabled" : undefined}
              rows={1}
            />
          </InputLayouts.Vertical>
        ) : (
          <TextFormField
            subtext={description}
            optional={field.optional}
            type={field.type}
            label={label}
            name={field.name}
            isTextArea={false}
            defaultHeight={"h-15"}
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
        <>INVALID FIELD TYPE</>
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
