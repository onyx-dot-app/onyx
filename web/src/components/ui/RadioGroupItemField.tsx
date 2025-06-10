import React from "react";
import { RadioGroupItem } from "@/components/ui/radio-group";

interface RadioGroupItemFieldProps {
  value: string;
  id: string;
  label: string;
  sublabel?: string;
}

export const RadioGroupItemField: React.FC<RadioGroupItemFieldProps> = ({
  value,
  id,
  label,
  sublabel,
}) => {
  const handleClick = () => {
    const radio = document.getElementById(id) as HTMLInputElement;
    if (radio) {
      radio.checked = true;
      radio.dispatchEvent(new Event("change", { bubbles: true }));
    }
  };

  return (
    <div className="flex items-start space-x-2">
      <RadioGroupItem value={value} id={id} className="mt-1" />
      <div className="flex flex-col">
        <label
          htmlFor={id}
          className="flex flex-col cursor-pointer"
          onClick={handleClick}
        >
          <span className="text-sm font-medium leading-none peer-disabled:cursor-not-allowed peer-disabled:opacity-70">
            {label}
          </span>
          {sublabel && (
            <span className="text-sm text-muted-foreground mt-1">
              {sublabel}
            </span>
          )}
        </label>
      </div>
    </div>
  );
};
