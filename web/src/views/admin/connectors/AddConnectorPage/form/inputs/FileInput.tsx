import { useField } from "formik";
import { useTranslations } from "next-intl";
import { useDropzone } from "react-dropzone";
import { Button, Text } from "@opal/components";
import { InputErrorText, InputVertical, Section } from "@opal/layouts";
import { SvgUploadCloud } from "@opal/icons";
import { cn, markdown } from "@opal/utils";

interface FileInputProps {
  name: string;
  label?: string;
  optional?: boolean;
  description?: string;
  multiple?: boolean;
  /** Takes one .zip file. */
  isZip?: boolean;
  hideError?: boolean;
  disabled?: boolean;
}

/**
 * A drop area with a file picker button. The field holds a `File[]`, or one
 * `File` (or null) when the input takes a single file.
 */
export default function FileInput({
  name,
  label,
  optional = false,
  description,
  multiple = true,
  isZip = false,
  hideError = false,
  disabled = false,
}: FileInputProps) {
  const t = useTranslations("admin.connectorsList.fileInput");
  const [field, meta, helpers] = useField<File | File[] | null | undefined>(
    name
  );
  const single = isZip || !multiple;
  const selectedFiles: File[] = Array.isArray(field.value)
    ? field.value
    : field.value
      ? [field.value]
      : [];

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    disabled,
    multiple: !single,
    noClick: true,
    noKeyboard: true,
    accept: isZip ? { "application/zip": [".zip"] } : undefined,
    onDrop: (files) => {
      void helpers.setTouched(true, false);
      void helpers.setValue(single ? (files[0] ?? null) : files);
    },
  });

  const chooseLabel = t("chooseButton.label", { multiple: String(!single) });
  const dropzone = (
    <div
      {...getRootProps()}
      className={cn(
        "flex w-full items-center gap-2 rounded-xl border border-dashed p-2",
        isDragActive
          ? "border-action-selection-05 bg-action-selection-01"
          : "border-border-01"
      )}
    >
      <input
        {...getInputProps({ id: name, "aria-label": label ?? chooseLabel })}
      />
      <Button
        type="button"
        icon={SvgUploadCloud}
        prominence="secondary"
        disabled={disabled}
        onClick={open}
      >
        {chooseLabel}
      </Button>
      <Text font="secondary-body" color="text-03">
        {selectedFiles.length > 0
          ? selectedFiles.map((file) => file.name).join(", ")
          : t("prompt", { multiple: String(!single) })}
      </Text>
    </div>
  );

  if (!label) {
    return (
      <Section gap={1} alignItems="start" width="full">
        {dropzone}
        {!hideError && meta.touched && meta.error && (
          <InputErrorText type="error">{meta.error}</InputErrorText>
        )}
      </Section>
    );
  }

  return (
    // With a label, the field name ties it to the file input's id and shows
    // the field's Formik error under it.
    <InputVertical
      withLabel={hideError ? false : name}
      disabled={disabled}
      title={label}
      subDescription={description ? markdown(description) : undefined}
      suffix={optional ? "optional" : undefined}
    >
      {dropzone}
    </InputVertical>
  );
}
