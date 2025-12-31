import { FormikProps, ErrorMessage } from "formik";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";
import { cn } from "@/lib/utils";
import { SvgX } from "@opal/icons";
export type GenericMultiSelectFormType<T extends string> = {
  [K in T]: number[];
};

interface GenericItem {
  id: number;
  name: string;
}

interface GenericMultiSelectProps<
  T extends string,
  F extends GenericMultiSelectFormType<T>,
> {
  formikProps: FormikProps<F>;
  fieldName: T;
  label: string;
  subtext?: string;
  items: GenericItem[] | undefined;
  isLoading: boolean;
  error: any;
  emptyMessage: string;
  disabled?: boolean;
  disabledMessage?: string;
}

export function GenericMultiSelect<
  T extends string,
  F extends GenericMultiSelectFormType<T>,
>({
  formikProps,
  fieldName,
  label,
  subtext,
  items,
  isLoading,
  error,
  emptyMessage,
  disabled = false,
  disabledMessage,
}: GenericMultiSelectProps<T, F>) {
  if (isLoading) {
    return (
      <div className="flex flex-col gap-2 w-full">
        <Text as="p" mainUiAction>
          {label}
        </Text>
        <div className="animate-pulse bg-background-neutral-02 h-10 w-full rounded-08" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col gap-2 w-full">
        <Text as="p" mainUiAction>
          {label}
        </Text>
        <Text as="p" text03 className="text-action-danger-05">
          Failed to load {label.toLowerCase()}. Please try again.
        </Text>
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="flex flex-col gap-2 w-full">
        <Text as="p" mainUiAction>
          {label}
        </Text>
        <Text as="p" text03>
          {emptyMessage}
        </Text>
      </div>
    );
  }

  const selectedIds = (formikProps.values[fieldName] as number[]) || [];
  const selectedItems = items.filter((item) => selectedIds.includes(item.id));

  const handleSelect = (option: { name: string; value: string | number }) => {
    if (disabled) return;
    const currentIds = (formikProps.values[fieldName] as number[]) || [];
    const numValue =
      typeof option.value === "string"
        ? parseInt(option.value, 10)
        : option.value;
    if (!currentIds.includes(numValue)) {
      formikProps.setFieldValue(fieldName, [...currentIds, numValue]);
    }
  };

  const handleRemove = (itemId: number) => {
    if (disabled) return;
    const currentIds = (formikProps.values[fieldName] as number[]) || [];
    formikProps.setFieldValue(
      fieldName,
      currentIds.filter((id) => id !== itemId)
    );
  };

  return (
    <div className="flex flex-col gap-2 w-full">
      <Text as="p" mainUiAction>
        {label}
      </Text>

      {subtext && (
        <Text as="p" text03>
          {disabled ? disabledMessage : subtext}
        </Text>
      )}

      <div className={cn(disabled && "opacity-50 pointer-events-none")}>
        <SearchMultiSelectDropdown
          options={items
            .filter((item) => !selectedIds.includes(item.id))
            .map((item) => ({
              name: item.name,
              value: item.id,
            }))}
          onSelect={handleSelect}
        />
      </div>

      {selectedItems.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {selectedItems.map((item) => (
            <Button
              key={item.id}
              secondary
              disabled={disabled}
              rightIcon={SvgX}
              onClick={() => handleRemove(item.id)}
              className="!px-2 !py-1"
            >
              {item.name}
            </Button>
          ))}
        </div>
      )}

      <ErrorMessage name={fieldName} component="div">
        {(msg) => (
          <Text as="p" text03 className="text-action-danger-05">
            {msg}
          </Text>
        )}
      </ErrorMessage>
    </div>
  );
}
