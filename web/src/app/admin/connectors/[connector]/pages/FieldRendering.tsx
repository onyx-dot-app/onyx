import React, { FC, useEffect } from "react";
import { AdminBooleanFormField } from "@/components/credentials/CredentialFields";
import { TabOption } from "@/lib/connectors/connectors";
import SelectInput from "./ConnectorInput/SelectInput";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField, MultiSelectField } from "@/components/Field";
import ListInput from "./ConnectorInput/ListInput";
import FileInput from "./ConnectorInput/FileInput";
import { ConfigurableSources } from "@/lib/types";
import { Credential } from "@/lib/connectors/credentials";
import CollapsibleSection from "@/app/admin/assistants/CollapsibleSection";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/fully_wrapped_tabs";
import { useFormikContext } from "formik";

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
  return (
    <div className="w-full">
      {tabField.label && (
        <div className="mb-4">
          <h3 className="text-lg font-semibold">
            {typeof tabField.label === "function"
              ? tabField.label(currentCredential)
              : tabField.label}
          </h3>
          {tabField.description && (
            <p className="text-sm text-muted-foreground mt-1">
              {typeof tabField.description === "function"
                ? tabField.description(currentCredential)
                : tabField.description}
            </p>
          )}
        </div>
      )}

      {/* Ensure there's at least one tab before rendering */}
      {tabField.tabs.length === 0 ? (
        <div className="text-sm text-muted-foreground">No tabs to display.</div>
      ) : (
        <Tabs
          defaultValue={tabField.tabs[0]?.value} // Optional chaining for safety, though the length check above handles it
          className="w-full"
          onValueChange={(newTab) => {
            // Clear values from other tabs but preserve defaults
            tabField.tabs.forEach((tab) => {
              if (tab.value !== newTab) {
                tab.fields.forEach((field) => {
                  // Only clear if not default value
                  if (values[field.name] !== field.default) {
                    values[field.name] = field.default;
                  }
                });
              }
            });
          }}
        >
          <TabsList>
            {tabField.tabs.map((tab) => (
              <TabsTrigger key={tab.value} value={tab.value}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {tabField.tabs.map((tab) => (
            <TabsContent key={tab.value} value={tab.value} className="">
              {tab.fields.map((subField, index, array) => {
                // Check visibility condition first
                if (
                  subField.visibleCondition &&
                  !subField.visibleCondition(values, currentCredential)
                ) {
                  return null;
                }

                return (
                  <div
                    key={subField.name}
                    className={
                      index < array.length - 1 && subField.type !== "string_tab"
                        ? "mb-4"
                        : ""
                    }
                  >
                    <RenderField
                      key={subField.name}
                      field={subField}
                      values={values}
                      connector={connector}
                      currentCredential={currentCredential}
                    />
                  </div>
                );
              })}
            </TabsContent>
          ))}
        </Tabs>
      )}
    </div>
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
  const { setFieldValue } = useFormikContext<any>(); // Get Formik's context functions

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
        <AdminBooleanFormField
          checked={values[field.name]}
          subtext={description}
          name={field.name}
          label={label}
          disabled={disabled}
          onChange={(e) => setFieldValue(field.name, e.target.value)}
        />
      ) : field.type === "text" ? (
        <TextFormField
          subtext={description}
          optional={field.optional}
          type={field.type}
          label={label}
          name={field.name}
          isTextArea={field.isTextArea || false}
          defaultHeight={"h-15"}
          disabled={disabled}
          onChange={(e) => setFieldValue(field.name, e.target.value)}
        />
      ) : field.type === "string_tab" ? (
        <div className="text-center">{description}</div>
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

  return <div key={field.name}>{fieldContent}</div>;
};
