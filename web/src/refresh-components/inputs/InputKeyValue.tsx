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
import { cn } from "@/lib/utils";
import InputTypeIn from "./InputTypeIn";
import { Button, EmptyMessageCard } from "@opal/components";
import type { WithoutStyles } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { ErrorTextLayout } from "@/layouts/input-layouts";
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
  return (
    <>
      <div className="flex flex-col gap-y-0.5">
        <InputTypeIn
          placeholder={keyPlaceholder || "Key"}
          value={item.key}
          onChange={(e) => onChange({ ...item, key: e.target.value })}
          aria-label={`${keyPlaceholder || "Key"} ${index + 1}`}
          aria-invalid={!!error?.key}
          showClearButton={false}
        />
        {error?.key && <ErrorTextLayout>{error.key}</ErrorTextLayout>}
      </div>
      <div className="flex flex-col gap-y-0.5">
        <InputTypeIn
          placeholder={valuePlaceholder || "Value"}
          value={item.value}
          onChange={(e) => onChange({ ...item, value: e.target.value })}
          aria-label={`${valuePlaceholder || "Value"} ${index + 1}`}
          aria-invalid={!!error?.value}
          showClearButton={false}
        />
        {error?.value && <ErrorTextLayout>{error.value}</ErrorTextLayout>}
      </div>
      <Button
        disabled={!canRemove}
        prominence="tertiary"
        icon={SvgMinusCircle}
        onClick={onRemove}
        aria-label={`Remove ${keyPlaceholder || "key-value"} pair ${index + 1}`}
      />
    </>
  );
}

export interface KeyValueInputProps
  extends WithoutStyles<
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
  keyTitle = "Key",
  valueTitle = "Value",
  keyPlaceholder = "Key",
  valuePlaceholder = "Value",
  items = [],
  onChange,
  mode = "line",
  layout = "equal",
  onValidationError,
  addButtonLabel = "Add Line",
  ...rest
}: KeyValueInputProps) {
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
          error.key = "Key cannot be empty";
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
            error.key = "Duplicate key";
          }
        });
      }
    });

    return errorsList;
  }, [items]);

  const hasAnyError = useMemo(() => {
    return errors.some((error) => error.key || error.value);
  }, [errors]);

  // Generate error message for external form libraries (Formik, etc.)
  const errorMessage = useMemo(() => {
    if (!hasAnyError) return null;

    const errorCount = errors.filter((e) => e.key || e.value).length;
    const duplicateCount = errors.filter(
      (e) => e.key === "Duplicate key"
    ).length;
    const emptyCount = errors.filter(
      (e) => e.key === "Key cannot be empty"
    ).length;

    if (duplicateCount > 0) {
      return `${duplicateCount} duplicate ${
        duplicateCount === 1 ? "key" : "keys"
      } found`;
    } else if (emptyCount > 0) {
      return `${emptyCount} empty ${emptyCount === 1 ? "key" : "keys"} found`;
    }
    return `${errorCount} validation ${
      errorCount === 1 ? "error" : "errors"
    } found`;
  }, [hasAnyError, errors]);

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
      aria-label={`${keyTitle} and ${valueTitle} pairs`}
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
          title="No items added yet."
          padding="sm"
          sizePreset="secondary"
        />
      )}

      <Button
        prominence="secondary"
        onClick={handleAdd}
        icon={SvgPlusCircle}
        aria-label={`Add ${keyTitle} and ${valueTitle} pair`}
        type="button"
      >
        {addButtonLabel}
      </Button>
    </div>
  );
}
