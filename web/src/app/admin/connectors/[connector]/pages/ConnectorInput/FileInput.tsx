import { useField } from "formik";
import { FileUpload } from "@/components/admin/connectors/FileUpload";
import CredentialSubText from "@/components/credentials/CredentialFields";

interface FileInputProps {
  name: string;
  label: string;
  optional?: boolean;
  description?: string;
}

export default function FileInput({
  name,
  label,
  optional = false,
  description,
}: FileInputProps) {
  const [field, meta, helpers] = useField(name);

  return (
    <>
      <label
        htmlFor={name}
        className="block text-sm font-medium text-text-700 mb-1"
      >
        {label}
        {optional && <span className="text-text-500 ml-1">(optional)</span>}
      </label>
      {description && <CredentialSubText>{description}</CredentialSubText>}
      <FileUpload
        selectedFiles={field.value ? [field.value] : []}
        setSelectedFiles={(files: File[]) => {
          helpers.setValue(files[0] || null);
        }}
      />
      {meta.touched && meta.error && (
        <div className="text-red-500 text-sm mt-1">{meta.error}</div>
      )}
    </>
  );
}
