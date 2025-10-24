import { FormikProps, ErrorMessage } from "formik";
import { Label } from "@/components/Field";
import Text from "@/refresh-components/texts/Text";
import { SearchMultiSelectDropdown } from "@/components/Dropdown";

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
}: GenericMultiSelectProps<T, F>) {
  if (isLoading) {
    return (
      <div className="mb-4">
        <Label>{label}</Label>
        <div className="animate-pulse bg-background-200 h-10 w-full rounded-lg mt-2"></div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-4">
        <Label>{label}</Label>
        <Text className="text-sm text-error mt-2">
          Failed to load {label.toLowerCase()}. Please try again.
        </Text>
      </div>
    );
  }

  if (!items || items.length === 0) {
    return (
      <div className="mb-4">
        <Label>{label}</Label>
        <Text className="text-sm text-text-subtle mt-2">{emptyMessage}</Text>
      </div>
    );
  }

  const selectedIds = (formikProps.values[fieldName] as number[]) || [];
  const selectedItems = items.filter((item) => selectedIds.includes(item.id));

  const handleSelect = (option: { name: string; value: string | number }) => {
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
    const currentIds = (formikProps.values[fieldName] as number[]) || [];
    formikProps.setFieldValue(
      fieldName,
      currentIds.filter((id) => id !== itemId)
    );
  };

  return (
    <div className="mb-4">
      <Label className="mb-2">{label}</Label>
      {subtext && (
        <Text className="text-sm text-text-subtle mb-3">{subtext}</Text>
      )}

      <SearchMultiSelectDropdown
        options={items
          .filter((item) => !selectedIds.includes(item.id))
          .map((item) => ({
            name: item.name,
            value: item.id,
          }))}
        onSelect={handleSelect}
      />

      {selectedItems.length > 0 && (
        <div className="flex flex-wrap gap-2 mt-3">
          {selectedItems.map((item) => (
            <div
              key={item.id}
              className="flex items-center gap-2 px-3 py-1.5 bg-background-125 border border-border rounded-md"
            >
              <span className="text-sm">{item.name}</span>
              <button
                type="button"
                onClick={() => handleRemove(item.id)}
                className="text-text-500 hover:text-error transition-colors"
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}

      <ErrorMessage
        name={fieldName}
        component="div"
        className="text-error text-sm mt-1"
      />
    </div>
  );
}
