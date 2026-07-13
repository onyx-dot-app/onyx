"use client";

import { useField } from "formik";
import { Checkbox, Text, Tooltip } from "@opal/components";

export interface LabeledCheckboxFieldProps {
  name: string;
  label: string;
  sublabel?: string;
  tooltip?: string;
  disabled?: boolean;
  onChange?: (checked: boolean) => void;
}

export function LabeledCheckboxField({
  name,
  label,
  sublabel,
  tooltip,
  disabled,
  onChange,
}: LabeledCheckboxFieldProps) {
  const [field, , helpers] = useField<boolean>({ name, type: "checkbox" });
  const labelId = `${name}-label`;

  function handleChange(checked: boolean) {
    helpers.setValue(checked);
    onChange?.(checked);
  }

  return (
    <Tooltip tooltip={tooltip} side="top" sideOffset={25}>
      <div className="flex w-fit items-start gap-x-2">
        <Checkbox
          id={name}
          aria-labelledby={labelId}
          checked={field.value}
          onCheckedChange={handleChange}
          disabled={disabled}
        />
        <label
          id={labelId}
          htmlFor={name}
          className="flex flex-col cursor-pointer"
        >
          <Text font="main-ui-action" color="text-04">
            {label}
          </Text>
          {sublabel && (
            <Text as="p" font="secondary-body" color="text-03">
              {sublabel}
            </Text>
          )}
        </label>
      </div>
    </Tooltip>
  );
}
