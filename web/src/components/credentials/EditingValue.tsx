import { useState } from "react";
import { SubLabel } from "../admin/connectors/Field";
import { EditIcon } from "../icons/icons";
import { AdminBooleanFormField, AdminTextField } from "./CredentialFields";

// Our own input component, to be used across forms
export const EditingValue: React.FC<{
  name: string;
  currentValue?: any;
  label: string;
  type?: string;
  includRevert?: boolean;
  className?: string;
  optional?: boolean;
  description?: string;
  setFieldValue: (field: string, value: any) => void;
  showNever?: boolean;

  // These are escape hatches from the overall
  // value editing component (when need to modify)
  options?: { value: string; label: string }[];
  onChange?: (value: string) => void;
  onChangeBool?: (value: boolean) => void;
  onChangeNumber?: (value: number) => void;
  onChangeDate?: (value: Date | null) => void;
}> = ({
  name,
  currentValue,
  label,
  options,
  type,
  includRevert,
  className,
  description,
  optional,
  setFieldValue,
  showNever,
  onChange,
  onChangeBool,
  onChangeNumber,
  onChangeDate,
}) => {
  const [value, setValue] = useState<boolean | string | number | Date>(
    currentValue
  );

  const updateValue = (newValue: string | boolean | number | Date) => {
    setValue(newValue);
    setFieldValue(name, newValue);
  };

  return (
    <div className="flex text-text-800 flex-col">
      <div className={`w-full flex gap-x-2 justify-between ${className}`}>
        <div className="text-sm w-full">
          {type === "checkbox" ? (
            <div className="flex items-center">
              <AdminBooleanFormField
                checked={currentValue as boolean}
                subtext={description}
                onChange={(e) => {
                  const newValue = e.target.checked;
                  updateValue(newValue);
                  if (onChangeBool) {
                    onChangeBool(newValue);
                  }
                }}
                name={name}
                label={label}
              />
            </div>
          ) : type === "date" ? (
            // Date handling
            <div>
              <label className="block text-sm font-medium text-text-700 mb-1">
                {label}
                {optional && (
                  <span className="text-text-500 ml-1">(optional)</span>
                )}
              </label>
              {description && <SubLabel>{description}</SubLabel>}

              <input
                type="date"
                name={name}
                value={
                  currentValue instanceof Date
                    ? currentValue.toISOString().split("T")[0]
                    : ""
                }
                placeholder={currentValue}
                onChange={(e) => {
                  const dateValue = e.target.value
                    ? new Date(e.target.value)
                    : null;
                  if (dateValue) {
                    updateValue(dateValue);
                  }
                  if (onChangeDate) {
                    onChangeDate(dateValue);
                  }
                }}
                className="mt-2 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md text-sm shadow-sm placeholder-gray-400
                    focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500
                    disabled:bg-gray-50 disabled:text-gray-500 disabled:border-gray-200 disabled:shadow-none
                    invalid:border-pink-500 invalid:text-pink-600
                    focus:invalid:border-pink-500 focus:invalid:ring-pink-500"
              />
            </div>
          ) : type === "number" ? (
            <>
              <label className="block text-sm font-medium text-text-700 mb-1">
                {label}
                {optional && (
                  <span className="text-text-500 ml-1">(optional)</span>
                )}
              </label>
              {description && <SubLabel>{description}</SubLabel>}

              <input
                type="number"
                name={name}
                value={value as number}
                placeholder={
                  currentValue === 0 && showNever
                    ? "Never"
                    : currentValue?.toString()
                }
                onChange={(e) => {
                  const inputValue = e.target.value;
                  if (inputValue === "") {
                    updateValue("");
                    if (onChangeNumber) {
                      onChangeNumber(0);
                    }
                  } else {
                    let value = Math.max(0, parseInt(inputValue));
                    if (!isNaN(value)) {
                      updateValue(value);
                      if (onChangeNumber) {
                        onChangeNumber(value);
                      }
                    }
                  }
                }}
                className={`mt-2 block w-full px-3 py-2 
                    bg-white border border-gray-300 rounded-md 
                    text-sm shadow-sm placeholder-gray-400
                    focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500
                    disabled:bg-gray-50 disabled:text-gray-500 disabled:border-gray-200 disabled:shadow-none
                    invalid:border-pink-500 invalid:text-pink-600
                    focus:invalid:border-pink-500 focus:invalid:ring-pink-500`}
              />
            </>
          ) : type === "select" ? (
            <div>
              <label className="block text-sm font-medium text-text-700 mb-1">
                {label}
                {optional && (
                  <span className="text-text-500 ml-1">(optional)</span>
                )}
              </label>
              {description && <SubLabel>{description}</SubLabel>}

              <select
                name={name}
                value={value as string}
                onChange={(e) => {
                  updateValue(e.target.value);
                  if (onChange) {
                    onChange(e.target.value);
                  }
                }}
                className="mt-2 block w-full px-3 py-2 bg-white border border-gray-300 rounded-md text-sm shadow-sm
                    focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500"
              >
                <option value="">Select an option</option>
                {options?.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            // Default
            <AdminTextField
              optional={optional}
              noPadding
              description={description}
              onChange={(e) => {
                updateValue(e.target.value);
                if (onChange) {
                  onChange(e.target.value!);
                }
              }}
              type={type}
              name={name}
              placeholder={currentValue}
              label={label}
            />
          )}
        </div>
        {includRevert && (
          <div className="flex-none mt-auto">
            <button
              className="text-xs h-[35px] my-auto p-1.5 rounded bg-background-900 border-border-dark text-text-300 flex gap-x-1"
              onClick={(e) => {
                updateValue("");
                e.preventDefault();
              }}
            >
              <EditIcon className="text-netural-300 my-auto" />
              <p className="my-auto">Revert</p>
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
