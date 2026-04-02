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

import React, {
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useId,
  useRef,
} from "react";
import { cn } from "@/lib/utils";
import InputTypeIn from "./InputTypeIn";
import { Button, EmptyMessageCard } from "@opal/components";
import type { WithoutStyles } from "@opal/types";
import Text from "@/refresh-components/texts/Text";
import { FieldContext } from "../form/FieldContext";
import { FieldMessage } from "../messages/FieldMessage";
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
  disabled?: boolean;
  onRemove: () => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  error?: KeyValueError;
  canRemove: boolean;
  index: number;
  fieldId: string;
}

function KeyValueInputItem({
  item,
  onChange,
  disabled,
  onRemove,
  keyPlaceholder,
  valuePlaceholder,
  error,
  canRemove,
  index,
  fieldId,
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
          aria-describedby={
            error?.key ? `${fieldId}-key-error-${index}` : undefined
          }
          variant={disabled ? "disabled" : undefined}
          showClearButton={false}
        />
        {error?.key && (
          <FieldMessage variant="error" className="ml-0.5">
            <FieldMessage.Content
              id={`${fieldId}-key-error-${index}`}
              role="alert"
              className="ml-0.5"
            >
              {error.key}
            </FieldMessage.Content>
          </FieldMessage>
        )}
      </div>
      <div className="flex flex-col gap-y-0.5">
        <InputTypeIn
          placeholder={valuePlaceholder || "Value"}
          value={item.value}
          onChange={(e) => onChange({ ...item, value: e.target.value })}
          aria-label={`${valuePlaceholder || "Value"} ${index + 1}`}
          aria-invalid={!!error?.value}
          aria-describedby={
            error?.value ? `${fieldId}-value-error-${index}` : undefined
          }
          variant={disabled ? "disabled" : undefined}
          showClearButton={false}
        />
        {error?.value && (
          <FieldMessage variant="error" className="ml-0.5">
            <FieldMessage.Content
              id={`${fieldId}-value-error-${index}`}
              role="alert"
              className="ml-0.5"
            >
              {error.value}
            </FieldMessage.Content>
          </FieldMessage>
        )}
      </div>
      <Button
        disabled={disabled || !canRemove}
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
  /** Array of key-value pairs */
  items: KeyValue[];
  /** Callback when items change */
  onChange: (nextItems: KeyValue[]) => void;
  /** Custom add handler */
  onAdd?: () => void;
  /** Custom remove handler */
  onRemove?: (index: number) => void;
  /** Disabled state */
  disabled?: boolean;
  /** Mode: 'line' allows removing all items, 'fixed-line' requires at least one item */
  mode?: "line" | "fixed-line";
  /** Layout: 'equal' - both inputs same width, 'key-wide' - key input is wider (60/40 split) */
  layout?: "equal" | "key-wide";
  /** Callback when validation state changes */
  onValidationChange?: (isValid: boolean, errors: KeyValueError[]) => void;
  /** Callback to handle validation errors - integrates with Formik or custom error handling. Called with error message when invalid, null when valid */
  onValidationError?: (errorMessage: string | null) => void;
  /** Optional custom validator for the key field. Return { isValid, message } */
  onKeyValidate?: (
    key: string,
    index: number,
    item: KeyValue,
    items: KeyValue[]
  ) => { isValid: boolean; message?: string };
  /** Optional custom validator for the value field. Return { isValid, message } */
  onValueValidate?: (
    value: string,
    index: number,
    item: KeyValue,
    items: KeyValue[]
  ) => { isValid: boolean; message?: string };
  /** Whether to validate for duplicate keys */
  validateDuplicateKeys?: boolean;
  /** Whether to validate for empty keys */
  validateEmptyKeys?: boolean;
  /** Optional name for the field (for accessibility) */
  name?: string;
  /** Custom label for the add button (defaults to "Add Line") */
  addButtonLabel?: string;
}

export default function KeyValueInput({
  keyTitle = "Key",
  valueTitle = "Value",
  items = [],
  onChange,
  onAdd,
  onRemove,
  disabled = false,
  mode = "line",
  layout = "equal",
  onValidationChange,
  onValidationError,
  onKeyValidate,
  onValueValidate,
  validateDuplicateKeys = true,
  validateEmptyKeys = true,
  name,
  addButtonLabel = "Add Line",
  ...rest
}: KeyValueInputProps) {
  // Try to get field context if used within FormField (safe access)
  const fieldContext = useContext(FieldContext);

  // Validation logic
  const errors = useMemo((): KeyValueError[] => {
    if (!items || items.length === 0) return [];

    const errorsList: KeyValueError[] = items.map(() => ({}));
    const keyCount = new Map<string, number[]>();

    items.forEach((item, index) => {
      // Validate empty keys - only if value is filled (user is actively working on this row)
      if (
        validateEmptyKeys &&
        item.key.trim() === "" &&
        item.value.trim() !== ""
      ) {
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

      // Custom key validation
      if (onKeyValidate) {
        const result = onKeyValidate(item.key, index, item, items);
        if (result && result.isValid === false) {
          const error = errorsList[index];
          if (error) {
            error.key = result.message || "Invalid key";
          }
        }
      }

      // Custom value validation
      if (onValueValidate) {
        const result = onValueValidate(item.value, index, item, items);
        if (result && result.isValid === false) {
          const error = errorsList[index];
          if (error) {
            error.value = result.message || "Invalid value";
          }
        }
      }
    });

    // Validate duplicate keys
    if (validateDuplicateKeys) {
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
    }

    return errorsList;
  }, [
    items,
    validateDuplicateKeys,
    validateEmptyKeys,
    onKeyValidate,
    onValueValidate,
  ]);

  const isValid = useMemo(() => {
    return errors.every((error) => !error.key && !error.value);
  }, [errors]);

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
  const onValidationChangeRef = useRef(onValidationChange);
  const onValidationErrorRef = useRef(onValidationError);

  useEffect(() => {
    onValidationChangeRef.current = onValidationChange;
  }, [onValidationChange]);

  useEffect(() => {
    onValidationErrorRef.current = onValidationError;
  }, [onValidationError]);

  useEffect(() => {
    onValidationChangeRef.current?.(isValid, errors);
  }, [isValid, errors]);

  // Notify parent of error state for form library integration
  useEffect(() => {
    onValidationErrorRef.current?.(errorMessage);
  }, [errorMessage]);

  const canRemoveItems = mode === "line" || items.length > 1;

  const handleAdd = useCallback(() => {
    if (onAdd) {
      onAdd();
      return;
    }
    onChange([...(items || []), { key: "", value: "" }]);
  }, [onAdd, onChange, items]);

  const handleRemove = useCallback(
    (index: number) => {
      if (!canRemoveItems && items.length === 1) return;

      if (onRemove) {
        onRemove(index);
        return;
      }
      const next = (items || []).filter((_, i) => i !== index);
      onChange(next);
    },
    [canRemoveItems, items, onRemove, onChange]
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

  const autoId = useId();
  const fieldId = fieldContext?.baseId || name || `key-value-input-${autoId}`;
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
              disabled={disabled}
              onRemove={() => handleRemove(index)}
              keyPlaceholder={keyTitle}
              valuePlaceholder={valueTitle}
              error={errors[index]}
              canRemove={canRemoveItems}
              index={index}
              fieldId={fieldId}
            />
          ))}
        </div>
      ) : (
        <EmptyMessageCard title="No items added yet." />
      )}

      <Button
        disabled={disabled}
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
