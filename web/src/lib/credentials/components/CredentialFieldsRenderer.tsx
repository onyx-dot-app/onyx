"use client";

import { useMemo } from "react";
import {
  InputPasswordTypeIn,
  InputSwitch,
  InputTypeIn,
  MessageCard,
  Tabs,
} from "@opal/components";
import {
  Content,
  InputHorizontal,
  InputVertical,
  Label,
  Section,
} from "@opal/layouts";
import { InputCheckboxField } from "@opal/form";
import type { IconFunctionComponent } from "@opal/types";
import { useFormikContext } from "formik";
import { useTranslations } from "next-intl";
import { TypedFileUploadFormField } from "@/components/Field";
import { FormikField } from "@/refresh-components/form/FormikField";
import { useCredentialFieldCopy } from "@/lib/credentials/hooks";
import { methodFields } from "@/lib/credentials/utils";
import type {
  CredentialFieldValues,
  CredentialSpec,
  CredentialSpecField,
} from "@/lib/credentials/types";
import type { ValidSources } from "@/lib/connectors/types/source";

interface CredentialFieldProps {
  source: ValidSources;
  fieldKey: string;
  field: CredentialSpecField;
}

/**
 * A checkbox bound to one Formik field, shaped as a `Content` icon so it sits
 * where an icon would. It depends only on the field name, so it keeps its
 * identity across renders and React never remounts the checkbox (which would
 * drop its focus on every toggle). The icon's class and size are not passed
 * on: the checkbox keeps its own colours and is already the icon's 1rem.
 */
function useCheckboxIcon(name: string): IconFunctionComponent {
  return useMemo(() => {
    function CheckboxIcon() {
      return <InputCheckboxField name={name} />;
    }
    return CheckboxIcon;
  }, [name]);
}

/** One field of a credential spec, drawn with the Opal input for its kind. */
function CredentialField({ source, fieldKey, field }: CredentialFieldProps) {
  const t = useTranslations("admin");
  const copy = useCredentialFieldCopy(source)(fieldKey);
  const label = copy.title;
  const checkboxIcon = useCheckboxIcon(fieldKey);

  // A file such as a .pfx key is binary; Opal's InputFile reads text, so
  // this field keeps the typed upload until Opal can hand back a File.
  if (field.kind === "file") {
    return <TypedFileUploadFormField name={fieldKey} label={label} />;
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
          name={fieldKey}
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
      : undefined;

  return (
    // The field name ties the label to the input's id and shows the field's
    // Formik error under it.
    <InputVertical
      withLabel={fieldKey}
      title={label}
      subDescription={subDescription}
    >
      <FormikField<string>
        name={fieldKey}
        render={(formikField, _helper, _meta, status) =>
          field.kind === "secret" ? (
            <InputPasswordTypeIn
              {...formikField}
              id={fieldKey}
              data-testid={fieldKey}
              value={formikField.value ?? ""}
              placeholder={placeholder}
              error={status === "error"}
            />
          ) : (
            <InputTypeIn
              {...formikField}
              id={fieldKey}
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

interface CredentialFieldsRendererProps {
  source: ValidSources;
  spec: CredentialSpec;
  authMethod?: string;
  setAuthMethod?: (method: string) => void;
}

export function CredentialFieldsRenderer({
  source,
  spec,
  authMethod,
  setAuthMethod,
}: CredentialFieldsRendererProps) {
  const t = useTranslations("admin");
  const { values, setValues } = useFormikContext<CredentialFieldValues>();
  const methods = spec.methods;

  // Switching auth method drops the fields only the other methods use.
  function handleAuthMethodChange(newMethod: string) {
    const kept = new Set(
      methods?.find((method) => method.value === newMethod)?.fields
    );
    const cleaned: CredentialFieldValues = {
      ...values,
      authentication_method: newMethod,
    };
    Object.keys(spec.fields).forEach((fieldKey) => {
      if (!kept.has(fieldKey)) delete cleaned[fieldKey];
    });
    setValues(cleaned);
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
              {methodFields(spec, method).map(([key, field]) => (
                <CredentialField
                  key={key}
                  source={source}
                  fieldKey={key}
                  field={field}
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
      {Object.entries(spec.fields).map(([key, field]) => (
        <CredentialField
          key={key}
          source={source}
          fieldKey={key}
          field={field}
        />
      ))}
    </>
  );
}
