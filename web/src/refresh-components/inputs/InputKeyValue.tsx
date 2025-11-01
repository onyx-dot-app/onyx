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

import React, { useCallback, useEffect, useMemo } from "react";
import { cn } from "@/lib/utils";
import InputTypeIn from "./InputTypeIn";
import SvgMinusCircle from "@/icons/minus-circle";
import SvgXOctagon from "@/icons/x-octagon";
import IconButton from "../buttons/IconButton";
import Button from "../buttons/Button";
import SvgPlusCircle from "@/icons/plus-circle";
import Text from "../texts/Text";
import { useFieldContext } from "../form/FieldContext";

export type KeyValue = { key: string; value: string };

type KeyValueError = {
  key?: string;
  value?: string;
};

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
  layout?: "equal" | "key-wide";
}

const KeyValueInputItem = ({
  item,
  onChange,
  disabled,
  onRemove,
  keyPlaceholder,
  valuePlaceholder,
  error,
  canRemove,
  index,
  layout = "equal",
}: KeyValueInputItemProps) => {
  // Layout classes: equal = both flex-1, key-wide = key gets more space (3/5 vs 2/5)
  const keyClassName = layout === "equal" ? "flex-1" : "flex-[3]";
  const valueClassName = layout === "equal" ? "flex-1" : "flex-[2]";

  return (
    <div className="flex gap-1 w-full">
      <div className="flex gap-2 flex-1">
        <div className={cn(keyClassName, "flex flex-col gap-y-0.5")}>
          <InputTypeIn
            placeholder={keyPlaceholder || "Key"}
            value={item.key}
            onChange={(e) => onChange({ ...item, key: e.target.value })}
            aria-label={`${keyPlaceholder || "Key"} ${index + 1}`}
            aria-invalid={!!error?.key}
            aria-describedby={error?.key ? `key-error-${index}` : undefined}
            disabled={disabled}
            showClearButton={false}
          />
          {error?.key && (
            <div className="flex flex-row items-center gap-x-0.5 ml-0.5">
              <div className="w-4 h-4 flex items-center justify-center">
                <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />
              </div>
              <Text
                id={`key-error-${index}`}
                text03
                secondaryBody
                className="ml-0.5"
                role="alert"
              >
                {error.key}
              </Text>
            </div>
          )}
        </div>
        <div className={cn(valueClassName, "flex flex-col gap-y-0.5")}>
          <InputTypeIn
            placeholder={valuePlaceholder || "Value"}
            value={item.value}
            onChange={(e) => onChange({ ...item, value: e.target.value })}
            aria-label={`${valuePlaceholder || "Value"} ${index + 1}`}
            aria-invalid={!!error?.value}
            aria-describedby={error?.value ? `value-error-${index}` : undefined}
            disabled={disabled}
            showClearButton={false}
          />
          {error?.value && (
            <div className="flex flex-row items-center gap-x-0.5 ml-0.5">
              <div className="w-4 h-4 flex items-center justify-center">
                <SvgXOctagon className="h-3 w-3 stroke-status-error-05" />
              </div>
              <Text
                id={`value-error-${index}`}
                text03
                secondaryBody
                className="ml-0.5"
                role="alert"
              >
                {error.value}
              </Text>
            </div>
          )}
        </div>
      </div>
      <div className="flex items-start pt-[2px]">
        <IconButton
          internal
          icon={SvgMinusCircle}
          onClick={onRemove}
          disabled={disabled || !canRemove}
          aria-label={`Remove ${keyPlaceholder || "key-value"} pair ${
            index + 1
          }`}
        />
      </div>
    </div>
  );
};

export interface KeyValueInputProps
  extends Omit<React.HTMLAttributes<HTMLDivElement>, "onChange"> {
  /** Title for the key column */
  keyTitle: string;
  /** Title for the value column */
  valueTitle: string;
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
  /** Whether to validate for duplicate keys */
  validateDuplicateKeys?: boolean;
  /** Whether to validate for empty keys */
  validateEmptyKeys?: boolean;
  /** Optional name for the field (for accessibility) */
  name?: string;
}

const KeyValueInput = ({
  keyTitle,
  valueTitle,
  items = [],
  onChange,
  onAdd,
  onRemove,
  disabled = false,
  mode = "line",
  layout = "equal",
  onValidationChange,
  onValidationError,
  validateDuplicateKeys = true,
  validateEmptyKeys = true,
  name,
  className,
  ...rest
}: KeyValueInputProps) => {
  // Try to get field context if used within FormField
  let fieldContext;
  try {
    fieldContext = useFieldContext();
  } catch {
    // Not used within FormField, that's fine
    fieldContext = null;
  }

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
  }, [items, validateDuplicateKeys, validateEmptyKeys]);

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
  useEffect(() => {
    onValidationChange?.(isValid, errors);
  }, [isValid, errors, onValidationChange]);

  // Notify parent of error state for form library integration
  useEffect(() => {
    onValidationError?.(errorMessage);
  }, [errorMessage, onValidationError]);

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

  const fieldId = fieldContext?.baseId || name || "key-value-input";

  // Header layout classes to match input layout
  const headerKeyClassName = layout === "equal" ? "flex-1" : "flex-[3]";
  const headerValueClassName = layout === "equal" ? "flex-1" : "flex-[2]";

  return (
    <div
      className={cn("w-full flex flex-col gap-y-2", className)}
      role="group"
      aria-labelledby={`${fieldId}-header`}
      {...rest}
    >
      <div id={`${fieldId}-header`} className="flex gap-1 items-center w-full">
        <div className="flex gap-2 flex-1">
          <Text text04 mainUiAction className={headerKeyClassName}>
            {keyTitle}
          </Text>
          <Text text04 mainUiAction className={headerValueClassName}>
            {valueTitle}
          </Text>
        </div>
        <div className="w-[1.5rem]" aria-hidden />
      </div>

      {items && items.length > 0 ? (
        <div
          className="flex flex-col gap-y-2"
          role="list"
          aria-label={`${keyTitle} and ${valueTitle} pairs`}
        >
          {items.map((item, index) => (
            <div key={index} role="listitem">
              <KeyValueInputItem
                item={item}
                onChange={(next) => handleItemChange(index, next)}
                disabled={disabled}
                onRemove={() => handleRemove(index)}
                keyPlaceholder={keyTitle}
                valuePlaceholder={valueTitle}
                error={errors[index]}
                canRemove={canRemoveItems}
                index={index}
                layout={layout}
              />
            </div>
          ))}
        </div>
      ) : (
        <Text text03 secondaryBody className="ml-0.5">
          No items added yet.
        </Text>
      )}

      <div>
        <Button
          onClick={handleAdd}
          secondary
          disabled={disabled}
          leftIcon={SvgPlusCircle}
          aria-label={`Add ${keyTitle} and ${valueTitle} pair`}
          type="button"
        >
          Add Line
        </Button>
      </div>
    </div>
  );
};

export default KeyValueInput;
