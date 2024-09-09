import { FileUpload } from "@/components/admin/connectors/FileUpload";
import CredentialSubText from "@/components/credentials/CredentialFields";

interface FileInputProps {
  name: string;
  label: string;
  optional?: boolean;
  description?: string;
  selectedFiles: File[];
  setSelectedFiles: (files: File[]) => void;
}

export default function FileInput({
  name,
  label,
  optional = false,
  description,
  selectedFiles,
  setSelectedFiles,
}: FileInputProps) {
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
        selectedFiles={selectedFiles}
        setSelectedFiles={setSelectedFiles}
      />
    </>
  );
}
