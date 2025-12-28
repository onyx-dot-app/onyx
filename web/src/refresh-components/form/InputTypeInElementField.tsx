"use client";

import { useField } from "formik";
import InputTypeIn, {
  InputTypeInProps,
} from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { SvgMinusCircle } from "@opal/icons";
import { useOnChangeEvent } from "@/hooks/formHooks";

export interface InputTypeInElementFieldProps
  extends Omit<InputTypeInProps, "value" | "onClear"> {
  name: string;
  onRemove?: () => void;
}

// This component should be used inside of a list in `formik`'s "Form" context.
export default function InputTypeInElementField({
  name,
  onRemove,
  onChange: onChangeProp,
  ...inputProps
}: InputTypeInElementFieldProps) {
  const [field, meta] = useField(name);
  const onChange = useOnChangeEvent(name, onChangeProp);
  const hasError = meta.touched && meta.error;
  const isEmpty = !field.value || field.value.trim() === "";

  return (
    <div className="flex flex-row items-center gap-1">
      {/* Input */}
      <InputTypeIn
        {...inputProps}
        id={name}
        name={name}
        value={field.value || ""}
        onChange={onChange}
        onBlur={field.onBlur}
        error={!!hasError}
        showClearButton={false}
      />
      <IconButton
        icon={SvgMinusCircle}
        tertiary
        disabled={!onRemove || isEmpty}
        onClick={onRemove}
        tooltip="Remove"
      />
    </div>
  );
}
