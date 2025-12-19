import { useState } from "react";
import { Label, ManualErrorMessage } from "@/components/Field";
import CreatableSelect from "react-select/creatable";
import Select from "react-select";
import { ErrorMessage } from "formik";

interface Option {
  value: string;
  label: string;
}

interface MultiSelectDropdownProps {
  name: string;
  label: string;
  options: Option[];
  creatable: boolean;
  initialSelectedOptions?: Option[];
  direction?: "top" | "bottom";
  onChange: (selected: Option[]) => void;
  onCreate?: (created_name: string) => Promise<Option>;
  error?: string;
}

const getReactSelectStyles = () => ({
  control: (base: any) => ({
    ...base,
    backgroundColor: "var(--background-neutral-00)",
    borderColor: "var(--border-03)",
    color: "var(--text-04)",
  }),
  menu: (base: any) => ({
    ...base,
    backgroundColor: "var(--background-neutral-00)",
    border: "1px solid var(--border-03)",
    borderRadius: "4px",
    overflow: "hidden",
  }),
  menuList: (base: any) => ({
    ...base,
    backgroundColor: "var(--background-neutral-00)",
  }),
  option: (base: any, state: any) => ({
    ...base,
    backgroundColor: state.isSelected
      ? "var(--background-150)"
      : state.isFocused
        ? "var(--background-100)"
        : "transparent",
    color: "var(--text-04)",
  }),
  multiValue: (base: any) => ({
    ...base,
    backgroundColor: "var(--background-150)",
  }),
  multiValueLabel: (base: any) => ({
    ...base,
    color: "var(--text-04)",
  }),
  multiValueRemove: (base: any) => ({
    ...base,
    color: "var(--text-04)",
    ":hover": {
      backgroundColor: "var(--background-200)",
      color: "var(--text-04)",
    },
  }),
  input: (base: any) => ({
    ...base,
    color: "var(--text-04)",
  }),
  placeholder: (base: any) => ({
    ...base,
    color: "var(--text-02)",
  }),
  singleValue: (base: any) => ({
    ...base,
    color: "var(--text-04)",
  }),
});

const MultiSelectDropdown = ({
  name,
  label,
  options,
  creatable,
  onChange,
  onCreate,
  error,
  direction = "bottom",
  initialSelectedOptions = [],
}: MultiSelectDropdownProps) => {
  const [selectedOptions, setSelectedOptions] = useState<Option[]>(
    initialSelectedOptions
  );
  const [allOptions, setAllOptions] = useState<Option[]>(options);
  const [inputValue, setInputValue] = useState("");

  const handleInputChange = (input: string) => {
    setInputValue(input);
  };

  const handleChange = (selected: any) => {
    setSelectedOptions(selected || []);
    onChange(selected || []);
  };

  const handleCreateOption = async (inputValue: string) => {
    if (creatable) {
      if (!onCreate) {
        console.error("onCreate is required for creatable");
        return;
      }
      try {
        const newOption = await onCreate(inputValue);
        if (newOption) {
          setAllOptions([...options, newOption]);
          setSelectedOptions([...selectedOptions, newOption]);
          onChange([...selectedOptions, newOption]);
        }
      } catch (error) {
        console.error("Error creating option:", error);
      }
    } else {
      return;
    }
  };

  return (
    <div className="flex flex-col text-white space-y-4 mb-4">
      <Label>{label}</Label>
      {creatable ? (
        <CreatableSelect
          isMulti
          options={allOptions}
          value={selectedOptions}
          onChange={handleChange}
          onCreateOption={handleCreateOption}
          onInputChange={handleInputChange}
          inputValue={inputValue}
          menuPlacement={direction}
          styles={getReactSelectStyles()}
        />
      ) : (
        <Select
          isMulti
          options={allOptions}
          value={selectedOptions}
          onChange={handleChange}
          onInputChange={handleInputChange}
          inputValue={inputValue}
          menuPlacement={direction}
          styles={getReactSelectStyles()}
        />
      )}
      {error ? (
        <ManualErrorMessage>{error}</ManualErrorMessage>
      ) : (
        <ErrorMessage
          name={name}
          component="div"
          className="text-red-500 text-sm mt-1"
        />
      )}
    </div>
  );
};

export default MultiSelectDropdown;
