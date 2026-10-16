"use client";

import type { RichStr } from "@opal/types";
import { InputVertical } from "@opal/layouts";
import InputTypeInField from "@/refresh-components/form/InputTypeInField";

interface ConfigTextFieldProps {
  title: string;
  placeholder: string;
  subDescription?: string | RichStr;
}

export function ConfigTextField({
  title,
  placeholder,
  subDescription,
}: ConfigTextFieldProps) {
  return (
    <InputVertical
      title={title}
      withLabel="config"
      subDescription={subDescription}
    >
      <InputTypeInField name="config" placeholder={placeholder} />
    </InputVertical>
  );
}
