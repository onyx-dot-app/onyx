"use client";

import { useField } from "formik";
import InputMultiUpload, {
  type InputMultiUploadProps,
} from "@opal/components/inputs/uploads/input-multi-upload/components";

/** Every `InputMultiUpload` prop except the files and their setter, which Formik owns. */
type InputMultiUploadFieldProps = Omit<
  InputMultiUploadProps,
  "value" | "onFilesChange"
> & {
  /** The Formik field name. */
  name: string;
};

/**
 * Formik-bound `InputMultiUpload` over a `File[]` field. With no files the
 * field holds `null`, so a required check fails. Adding or removing a file
 * marks the field touched, as leaving it does; a touched field with an error
 * shows the error variant unless `variant` is set.
 */
function InputMultiUploadField({
  name,
  variant,
  onBlur,
  ...props
}: InputMultiUploadFieldProps) {
  const [field, meta, helpers] = useField<File[] | null>(name);
  const isError: boolean = !!meta.touched && meta.error !== undefined;
  return (
    <InputMultiUpload
      {...props}
      id={props.id ?? name}
      name={name}
      variant={variant ?? (isError ? "error" : "primary")}
      onBlur={(event) => {
        onBlur?.(event);
        void helpers.setTouched(true);
      }}
      value={Array.isArray(field.value) ? field.value : []}
      onFilesChange={(files) => {
        // setValue validates with the new value; setTouched must not
        // validate again with the pre-change values.
        void helpers.setValue(files.length > 0 ? files : null);
        void helpers.setTouched(true, false);
      }}
    />
  );
}

export { InputMultiUploadField, type InputMultiUploadFieldProps };
