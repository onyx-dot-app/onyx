import {
  ArrayHelpers,
  ErrorMessage,
  FieldArray,
  getIn,
  useFormikContext,
} from "formik";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { InputErrorText, InputVertical, Section } from "@opal/layouts";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import { useStableRowKeys } from "@/views/admin/connectors/AddConnectorPage/form/inputs/useStableRowKeys";

interface ListInputProps {
  name: string;
  label: string;
  description?: string;
  optional?: boolean;
  disabled?: boolean;
}

/** A list of strings, one text input per row, with add and remove buttons. */
export default function ListInput({
  name,
  label,
  description,
  optional,
  disabled,
}: ListInputProps) {
  const t = useTranslations("admin.connectorsList.listInput");
  const { values, errors, touched } =
    useFormikContext<Record<string, unknown>>();
  const rawItems: unknown = getIn(values, name);
  const items: unknown[] = Array.isArray(rawItems) ? rawItems : [];
  const rowKeys = useStableRowKeys(items.length);

  // An error on the whole list, such as "at least one is required".
  const listError: unknown = getIn(errors, name);
  const listErrorText =
    getIn(touched, name) && typeof listError === "string"
      ? listError
      : undefined;

  return (
    <InputVertical
      title={label}
      description={description}
      suffix={optional ? "optional" : undefined}
      disabled={disabled}
    >
      <FieldArray
        name={name}
        render={(arrayHelpers: ArrayHelpers) => (
          <Section gap={2} alignItems="start" width="full">
            {items.map((_, index) => (
              <Section
                key={rowKeys.keys[index]}
                gap={1}
                alignItems="start"
                width="full"
              >
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  alignItems="center"
                  gap={1}
                  width="full"
                >
                  <InputTypeInField
                    name={`${name}.${index}`}
                    placeholder={t("placeholder", {
                      label: label.toLowerCase(),
                    })}
                    variant={disabled ? "disabled" : undefined}
                    autoComplete="off"
                  />
                  <Button
                    icon={SvgMinusCircle}
                    prominence="tertiary"
                    size="sm"
                    type="button"
                    disabled={disabled}
                    tooltip={t("removeButton.tooltip")}
                    onClick={() => {
                      rowKeys.removeKey(index);
                      arrayHelpers.remove(index);
                    }}
                  />
                </Section>
                <ErrorMessage
                  name={`${name}.${index}`}
                  render={(msg) => (
                    <InputErrorText type="error">{msg}</InputErrorText>
                  )}
                />
              </Section>
            ))}

            <Button
              icon={SvgPlusCircle}
              prominence="secondary"
              type="button"
              disabled={disabled}
              onClick={() => arrayHelpers.push("")}
            >
              {t("addButton.label")}
            </Button>

            {listErrorText && (
              <InputErrorText type="error">{listErrorText}</InputErrorText>
            )}
          </Section>
        )}
      />
    </InputVertical>
  );
}
