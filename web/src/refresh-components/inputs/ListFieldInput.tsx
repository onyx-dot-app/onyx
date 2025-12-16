import { useState, KeyboardEvent } from "react";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Button from "@/refresh-components/buttons/Button";
import { SvgX } from "@opal/icons";
interface ListFieldInputProps {
  values: string[];
  onChange: (values: string[]) => void;
  placeholder?: string;
  disabled?: boolean;
}

/**
 * ListFieldInput is a component that allows the user to input a list of values by typing and pressing Enter.
 * It displays the values in a list of chips, and allows the user to add and remove values.

 * @param values - The array of values to display in the input field.
 * @param onChange - The function to call when the value changes.
 * @param placeholder - The placeholder text to display in the input field.
 * @param disabled - Whether the input field is disabled.
 **/
export function ListFieldInput({
  values,
  onChange,
  placeholder = "",
  disabled = false,
}: ListFieldInputProps) {
  const [inputValue, setInputValue] = useState("");

  const handleKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter" && inputValue.trim()) {
      e.preventDefault();
      const trimmedValue = inputValue.trim();

      // Avoid duplicates
      if (!values.includes(trimmedValue)) {
        onChange([...values, trimmedValue]);
      }

      setInputValue("");
    }
  };

  const removeValue = (indexToRemove: number) => {
    onChange(values.filter((_, index) => index !== indexToRemove));
  };

  return (
    <div className="flex flex-col w-full space-y-2 mb-4">
      <InputTypeIn
        placeholder={placeholder}
        value={inputValue}
        disabled={disabled}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyDown={handleKeyDown}
      />

      <div className="mt-3">
        <div className="flex flex-wrap gap-1.5">
          {values.map((value, index) => (
            <Button
              key={index}
              internal
              secondary
              type="button"
              aria-label={`Remove ${value}`}
              onClick={() => removeValue(index)}
              rightIcon={SvgX}
              className="rounded h-8"
            >
              {value}
            </Button>
          ))}
        </div>
      </div>
    </div>
  );
}
