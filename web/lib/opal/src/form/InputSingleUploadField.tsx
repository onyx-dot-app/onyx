"use client";

import { useField } from "formik";
import InputSingleUpload, {
  type InputSingleUploadFileProps,
  type InputSingleUploadTextProps,
} from "@opal/components/inputs/uploads/input-single-upload/components";
import type { DistributiveOmit } from "@opal/types";

/** Every `InputSingleUpload` prop except the value and its setter, which Formik owns. */
type InputSingleUploadFieldProps = (
  | DistributiveOmit<InputSingleUploadTextProps, "value" | "setValue">
  | DistributiveOmit<InputSingleUploadFileProps, "value" | "onFileChange">
) & {
  /** The Formik field name. */
  name: string;
};

/**
 * Formik-bound `InputSingleUpload`. Text mode holds a `string` field (the uploaded
 * file's text, or pasted text); `mode="file"` holds a `File | null` field.
 * An upload, a paste or a clear marks the field touched, as leaving it does;
 * a touched field with an error shows the error variant unless `variant` is
 * set.
 */
function InputSingleUploadField({
  name,
  variant,
  onBlur,
  ...props
}: InputSingleUploadFieldProps) {
  const [field, meta, helpers] = useField<unknown>(name);
  const isError: boolean = !!meta.touched && meta.error !== undefined;
  const shared = {
    id: props.id ?? name,
    name,
    variant: variant ?? (isError ? "error" : "primary"),
    onBlur: (event: React.FocusEvent<HTMLElement>) => {
      onBlur?.(event);
      void helpers.setTouched(true);
    },
  } as const;

  // setValue validates with the new value; setTouched must not validate again
  // with the pre-change values.
  if (props.mode === "file") {
    return (
      <InputSingleUpload
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
    <InputSingleUpload
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

export { InputSingleUploadField, type InputSingleUploadFieldProps };
