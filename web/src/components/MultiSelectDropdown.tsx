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
          className="react-select-container"
          classNamePrefix="react-select"
          menuPlacement={direction}
        />
      ) : (
        <Select
          isMulti
          options={allOptions}
          value={selectedOptions}
          onChange={handleChange}
          onInputChange={handleInputChange}
          inputValue={inputValue}
          className="react-select-container"
          classNamePrefix="react-select"
          menuPlacement={direction}
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
