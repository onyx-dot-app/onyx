"use client";

import { useState } from "react";
import { Label, ManualErrorMessage } from "./admin/connectors/Field";
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
      // Support entering multiple values separated by commas or spaces
      const tokens = inputValue
        .split(/[\s,]+/)
        .map((t) => t.trim())
        .filter((t) => t.length > 0);

      // If a custom onCreate is provided, create each token through it; otherwise create locally
      const createOne = async (token: string): Promise<Option | null> => {
        if (onCreate) {
          try {
            const created = await onCreate(token);
            return created || null;
          } catch (error) {
            console.error("Error creating option:", error);
            return null;
          }
        }
        return { value: token, label: token };
      };

      const createdOptions: Option[] = [];
      for (const token of tokens) {
        const created = await createOne(token);
        if (created) {
          createdOptions.push(created);
        }
      }

      if (createdOptions.length > 0) {
        const newAll = [...allOptions];
        const newSelected = [...selectedOptions];
        createdOptions.forEach((opt) => {
          // avoid duplicates by value
          const existsInAll = newAll.some((o) => o.value === opt.value);
          if (!existsInAll) newAll.push(opt);
          const existsInSel = newSelected.some((o) => o.value === opt.value);
          if (!existsInSel) newSelected.push(opt);
        });
        setAllOptions(newAll);
        setSelectedOptions(newSelected);
        onChange(newSelected);
      }
    } else {
      return;
    }
  };

  return (
    <div className="flex flex-col space-y-4 mb-4">
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
