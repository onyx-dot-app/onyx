"use client";

/**
 * KeyValueInput - A comprehensive key-value pair input component
 *
 * Features:
 * - Two modes: 'line' (can remove all) and 'fixed-line' (minimum 1 item)
 * - Built-in validation for duplicate keys and empty keys
 * - Full accessibility with ARIA support
 * - Integrates with Formik, FormField, and custom form libraries
 * - Inline error display with danger-colored borders
 *
 * @example Basic Usage
 * ```tsx
 * const [items, setItems] = useState([{ key: "API_KEY", value: "value" }]);
 *
 * <KeyValueInput
 *   keyTitle="Variable Name"
 *   valueTitle="Value"
 *   items={items}
 *   onChange={setItems}
 *   mode="line"
 * />
 * ```
 *
 * @example With Formik Integration
 * ```tsx
 * <Formik initialValues={{ envVars: [] }}>
 *   {({ values, setFieldValue, setFieldError }) => (
 *     <FormField state={errors.envVars ? "error" : "idle"}>
 *       <FormField.Label>Environment Variables</FormField.Label>
 *       <FormField.Control asChild>
 *         <KeyValueInput
 *           keyTitle="Variable Name"
 *           valueTitle="Value"
 *           items={values.envVars}
 *           onChange={(items) => setFieldValue("envVars", items)}
 *           onValidationError={(error) => {
 *             if (error) {
 *               setFieldError("envVars", error);
 *             } else {
 *               setFieldError("envVars", undefined);
 *             }
 *           }}
 *         />
 *       </FormField.Control>
 *     </FormField>
 *   )}
 * </Formik>
 * ```
 *
 * @example With Local Error State
 * ```tsx
 * const [error, setError] = useState<string | null>(null);
 *
 * <FormField state={error ? "error" : "idle"}>
 *   <FormField.Label>Headers</FormField.Label>
 *   <FormField.Control asChild>
 *     <KeyValueInput
 *       keyTitle="Header"
 *       valueTitle="Value"
 *       items={headers}
 *       onChange={setHeaders}
 *       onValidationError={setError}
 *     />
 *   </FormField.Control>
 * </FormField>
 * ```
 */

import React, { useCallback, useEffect, useMemo, useRef } from "react";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { InputTypeIn } from "@opal/components";
import { Button, EmptyMessageCard } from "@opal/components";
import type { WithoutStyles } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { InputErrorText } from "@opal/layouts";
import { SvgMinusCircle, SvgPlusCircle } from "@opal/icons";

export type KeyValue = { key: string; value: string };

type KeyValueError = {
  key?: string;
  value?: string;
};

/*
 * CSS Grid is used instead of flexbox so that the key column, value column,
 * and remove button stay perfectly aligned across every row — including the
 * header titles. With flex + width restrictions each row is laid out
 * independently, so columns can drift when content (e.g. validation errors)
 * causes one cell to grow. Grid's shared column tracks prevent that.
 */
const GRID_COLS = {
  equal: "grid-cols-[1fr_1fr_2.25rem]",
  "key-wide": "grid-cols-[3fr_2fr_2.25rem]",
} as const;

interface KeyValueInputItemProps {
  item: KeyValue;
  onChange: (next: KeyValue) => void;
  onRemove: () => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  error?: KeyValueError;
  canRemove: boolean;
  index: number;
}

function KeyValueInputItem({
  item,
  onChange,
  onRemove,
  keyPlaceholder,
  valuePlaceholder,
  error,
  canRemove,
  index,
}: KeyValueInputItemProps) {
  const t = useTranslations("common.keyValue");
  return (
    <>
      <div className="flex flex-col gap-y-0.5">
        <InputTypeIn
          placeholder={keyPlaceholder}
          value={item.key}
          onChange={(e) => onChange({ ...item, key: e.target.value })}
          aria-label={t("input.ariaLabel", {
            label: keyPlaceholder || t("keyColumn.title"),
            index: index + 1,
          })}
          aria-invalid={!!error?.key}
        />
        {error?.key && <InputErrorText>{error.key}</InputErrorText>}
      </div>
      <div className="flex flex-col gap-y-0.5">
        <InputTypeIn
          placeholder={valuePlaceholder}
          value={item.value}
          onChange={(e) => onChange({ ...item, value: e.target.value })}
          aria-label={t("input.ariaLabel", {
            label: valuePlaceholder || t("valueColumn.title"),
            index: index + 1,
          })}
          aria-invalid={!!error?.value}
        />
        {error?.value && <InputErrorText>{error.value}</InputErrorText>}
      </div>
      <Button
        disabled={!canRemove}
        prominence="tertiary"
        icon={SvgMinusCircle}
        onClick={onRemove}
        aria-label={t("removeButton.ariaLabel", {
          label: keyPlaceholder || t("pair.fallbackLabel"),
          index: index + 1,
        })}
      />
    </>
  );
}

export interface KeyValueInputProps extends WithoutStyles<
  Omit<React.HTMLAttributes<HTMLDivElement>, "onChange">
> {
  /** Title for the key column */
  keyTitle?: string;

  /** Title for the value column */
  valueTitle?: string;

  /** Placeholder for the key input */
  keyPlaceholder?: string;

  /** Placeholder for the value input */
  valuePlaceholder?: string;

  /** Array of key-value pairs */
  items: KeyValue[];

  /** Callback when items change */
  onChange: (nextItems: KeyValue[]) => void;

  /** Mode: 'line' allows removing all items, 'fixed-line' requires at least one item */
  mode?: "line" | "fixed-line";

  /** Layout: 'equal' - both inputs same width, 'key-wide' - key input is wider (60/40 split) */
  layout?: "equal" | "key-wide";

  /** Callback to handle validation errors - integrates with Formik or custom error handling. Called with error message when invalid, null when valid */
  onValidationError?: (errorMessage: string | null) => void;

  /** Custom label for the add button (defaults to "Add Line") */
  addButtonLabel?: string;
}

export default function KeyValueInput({
  keyTitle: keyTitleProp,
  valueTitle: valueTitleProp,
  keyPlaceholder,
  valuePlaceholder,
  items = [],
  onChange,
  mode = "line",
  layout = "equal",
  onValidationError,
  addButtonLabel: addButtonLabelProp,
  ...rest
}: KeyValueInputProps) {
  const t = useTranslations("common.keyValue");
  const keyTitle = keyTitleProp ?? t("keyColumn.title");
  const valueTitle = valueTitleProp ?? t("valueColumn.title");
  const addButtonLabel = addButtonLabelProp ?? t("addButton.label");
  // Row errors and the summary both compare against these translated
  // messages, so the strings stay consistent within a render.
  const emptyKeyMessage = t("error.emptyKey");
  const duplicateKeyMessage = t("error.duplicateKey");

  // Validation logic
  const errors = useMemo((): KeyValueError[] => {
    if (!items || items.length === 0) return [];

    const errorsList: KeyValueError[] = items.map(() => ({}));
    const keyCount = new Map<string, number[]>();

    items.forEach((item, index) => {
      // Validate empty keys
      if (item.key.trim() === "" && item.value.trim() !== "") {
        const error = errorsList[index];
        if (error) {
          error.key = emptyKeyMessage;
        }
      }

      // Track key occurrences for duplicate validation
      if (item.key.trim() !== "") {
        const existing = keyCount.get(item.key) || [];
        existing.push(index);
        keyCount.set(item.key, existing);
      }
    });

    // Validate duplicate keys
    keyCount.forEach((indices, key) => {
      if (indices.length > 1) {
        indices.forEach((index) => {
          const error = errorsList[index];
          if (error) {
            error.key = duplicateKeyMessage;
          }
        });
      }
    });

    return errorsList;
  }, [items, emptyKeyMessage, duplicateKeyMessage]);

  const hasAnyError = useMemo(() => {
    return errors.some((error) => error.key || error.value);
  }, [errors]);

  // Generate error message for external form libraries (Formik, etc.)
  const errorMessage = useMemo(() => {
    if (!hasAnyError) return null;

    const errorCount = errors.filter((e) => e.key || e.value).length;
    const duplicateCount = errors.filter(
      (e) => e.key === duplicateKeyMessage
    ).length;
    const emptyCount = errors.filter((e) => e.key === emptyKeyMessage).length;

    if (duplicateCount > 0) {
      return t("error.duplicateSummary", { count: duplicateCount });
    } else if (emptyCount > 0) {
      return t("error.emptySummary", { count: emptyCount });
    }
    return t("error.validationSummary", { count: errorCount });
  }, [hasAnyError, errors, duplicateKeyMessage, emptyKeyMessage, t]);

  // Notify parent of validation changes
  const onValidationErrorRef = useRef(onValidationError);

  useEffect(() => {
    onValidationErrorRef.current = onValidationError;
  }, [onValidationError]);

  // Notify parent of error state for form library integration
  useEffect(() => {
    onValidationErrorRef.current?.(errorMessage);
  }, [errorMessage]);

  const canRemoveItems = mode === "line" || items.length > 1;

  const handleAdd = useCallback(() => {
    onChange([...(items || []), { key: "", value: "" }]);
  }, [onChange, items]);

  const handleRemove = useCallback(
    (index: number) => {
      if (!canRemoveItems && items.length === 1) return;

      const next = (items || []).filter((_, i) => i !== index);
      onChange(next);
    },
    [canRemoveItems, items, onChange]
  );

  const handleItemChange = useCallback(
    (index: number, nextItem: KeyValue) => {
      const next = [...(items || [])];
      next[index] = nextItem;
      onChange(next);
    },
    [items, onChange]
  );

  // Initialize with at least one item for fixed-line mode
  useEffect(() => {
    if (mode === "fixed-line" && (!items || items.length === 0)) {
      onChange([{ key: "", value: "" }]);
    }
  }, [mode]); // Only run on mode change

  const gridCols = GRID_COLS[layout];

  return (
    <div
      className="w-full flex flex-col gap-y-2"
      role="group"
      aria-label={t("group.ariaLabel", { keyTitle, valueTitle })}
      {...rest}
    >
      {items && items.length > 0 ? (
        <div className={cn("grid items-start gap-1", gridCols)}>
          {/*
            # NOTE (@raunakab)
            We add this space below the "title"-row to add some breathing room between the titles and the key-value items.
            Since we're using a `grid` template, the padding below *one* item in a row applies additional height to *all* items in that row.
          */}
          <div className="pb-1">
            <Text mainUiAction>{keyTitle}</Text>
          </div>
          <Text mainUiAction>{valueTitle}</Text>
          <div aria-hidden />

          {items.map((item, index) => (
            <KeyValueInputItem
              key={index}
              item={item}
              onChange={(next) => handleItemChange(index, next)}
              onRemove={() => handleRemove(index)}
              keyPlaceholder={keyPlaceholder}
              valuePlaceholder={valuePlaceholder}
              error={errors[index]}
              canRemove={canRemoveItems}
              index={index}
            />
          ))}
        </div>
      ) : (
        <EmptyMessageCard
          title={t("empty.title")}
          padding={2}
          sizePreset="secondary"
        />
      )}

      <Button
        prominence="secondary"
        onClick={handleAdd}
        icon={SvgPlusCircle}
        aria-label={t("addButton.ariaLabel", { keyTitle, valueTitle })}
        type="button"
      >
        {addButtonLabel}
      </Button>
    </div>
  );
}
