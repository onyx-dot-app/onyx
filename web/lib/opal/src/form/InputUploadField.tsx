"use client";

import { useField } from "formik";
import InputUpload, {
  type InputUploadFileProps,
  type InputUploadTextProps,
} from "@opal/components/inputs/input-upload/components";
import type { DistributiveOmit } from "@opal/types";

/** Every `InputUpload` prop except the value and its setter, which Formik owns. */
type InputUploadFieldProps = (
  | DistributiveOmit<InputUploadTextProps, "value" | "setValue">
  | DistributiveOmit<InputUploadFileProps, "value" | "onFileChange">
) & {
  /** The Formik field name. */
  name: string;
};

/**
 * Formik-bound `InputUpload`. Text mode holds a `string` field (the uploaded
 * file's text, or pasted text); `mode="file"` holds a `File | null` field.
 * An upload, a paste or a clear marks the field touched, as leaving it does;
 * a touched field with an error shows the error variant unless `variant` is
 * set.
 */
function InputUploadField({
  name,
  variant,
  onBlur,
  ...props
}: InputUploadFieldProps) {
  const [field, meta, helpers] = useField<unknown>(name);
  const isError: boolean = !!meta.touched && meta.error !== undefined;
  const shared = {
    id: props.id ?? name,
    name,
    variant: variant ?? (isError ? "error" : "primary"),
    onBlur: (event: React.FocusEvent<HTMLButtonElement>) => {
      onBlur?.(event);
      void helpers.setTouched(true);
    },
  } as const;

  // setValue validates with the new value; setTouched must not validate again
  // with the pre-change values.
  if (props.mode === "file") {
    return (
      <InputUpload
        {...props}
        {...shared}
        value={field.value instanceof File ? field.value : null}
        onFileChange={(file: File | null) => {
          void helpers.setValue(file);
          void helpers.setTouched(true, false);
        }}
      />
    );
  }
  return (
    <InputUpload
      {...props}
      {...shared}
      value={typeof field.value === "string" ? field.value : ""}
      setValue={(value: string) => {
        void helpers.setValue(value);
        void helpers.setTouched(true, false);
      }}
    />
  );
}

export { InputUploadField, type InputUploadFieldProps };
