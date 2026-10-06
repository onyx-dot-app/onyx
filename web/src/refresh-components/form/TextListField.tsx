"use client";

import { useState } from "react";
import {
  ArrayHelpers,
  ErrorMessage,
  FieldArray,
  getIn,
  useFormikContext,
} from "formik";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { InputErrorText, Section } from "@opal/layouts";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

interface StableRowKeys {
  /** One React key per row, in row order. */
  keys: number[];
  /** Drops the key of the row at `index`. Call it with the row's removal. */
  removeKey: (index: number) => void;
}

/**
 * Stable per-row keys, so removing a middle row doesn't shift native input
 * state (focus, autofill) onto the row that takes its index. Index keys
 * would; content-derived keys would remount the row on every keystroke.
 */
function useStableRowKeys(rowCount: number): StableRowKeys {
  const [state, setState] = useState<{ keys: number[]; nextKey: number }>({
    keys: Array.from({ length: rowCount }, (_, index) => index),
    nextKey: rowCount,
  });

  if (state.keys.length < rowCount) {
    const keysToAdd: number = rowCount - state.keys.length;
    setState({
      keys: [
        ...state.keys,
        ...Array.from(
          { length: keysToAdd },
          (_, index) => state.nextKey + index
        ),
      ],
      nextKey: state.nextKey + keysToAdd,
    });
  } else if (state.keys.length > rowCount) {
    setState({ keys: state.keys.slice(0, rowCount), nextKey: state.nextKey });
  }

  function removeKey(index: number) {
    setState((prev) => ({
      keys: prev.keys.filter((_, i) => i !== index),
      nextKey: prev.nextKey,
    }));
  }

  return { keys: state.keys, removeKey };
}

export interface TextListFieldProps {
  /** The Formik field name. Its value is a `string[]`. */
  name: string;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * Formik-bound list of strings: one text input per row, with add and remove
 * buttons. Shows each row's error under it, and an error on the whole list
 * under the add button.
 */
export default function TextListField({
  name,
  placeholder,
  disabled,
}: TextListFieldProps) {
  const t = useTranslations("common.textListField");
  const { values, errors, touched } =
    useFormikContext<Record<string, unknown>>();
  const rawItems: unknown = getIn(values, name);
  const items: unknown[] = Array.isArray(rawItems) ? rawItems : [];
  const rowKeys: StableRowKeys = useStableRowKeys(items.length);

  const listError: unknown = getIn(errors, name);
  const listErrorText: string | undefined =
    getIn(touched, name) && typeof listError === "string"
      ? listError
      : undefined;

  return (
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
                  placeholder={placeholder}
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
  );
}
