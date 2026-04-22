import { markdown } from "@opal/utils";
import { Text } from "@opal/components";
import { InputVertical } from "@opal/layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import PasswordInputTypeIn from "@/refresh-components/inputs/PasswordInputTypeIn";

// ---------------------------------------------------------------------------
// Credential form field components
// ---------------------------------------------------------------------------

interface ApiKeyFieldProps {
  apiLink: string;
  providerName: string;
  value: string;
  onChange: (value: string) => void;
}

export function ApiKeyField({
  apiLink,
  providerName,
  value,
  onChange,
}: ApiKeyFieldProps) {
  return (
    <InputVertical
      title="API Key"
      subDescription={markdown(
        `Paste your [API key](${apiLink}) from ${providerName} to access your models.`
      )}
    >
      <PasswordInputTypeIn
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </InputVertical>
  );
}

interface ApiUrlFieldProps {
  title: string;
  placeholder: string;
  subDescription?: string;
  value: string;
  onChange: (value: string) => void;
}

export function ApiUrlField({
  title,
  placeholder,
  subDescription,
  value,
  onChange,
}: ApiUrlFieldProps) {
  return (
    <InputVertical title={title} subDescription={subDescription}>
      <InputTypeIn
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </InputVertical>
  );
}

interface GoogleCredentialsFieldProps {
  fileInputRef: React.RefObject<HTMLInputElement | null>;
  fileName: string;
  onFileUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
}

export function GoogleCredentialsField({
  fileInputRef,
  fileName,
  onFileUpload,
}: GoogleCredentialsFieldProps) {
  return (
    <InputVertical title="Upload JSON credentials file">
      <input
        ref={fileInputRef}
        type="file"
        accept=".json"
        onChange={onFileUpload}
      />
      {fileName && (
        <Text font="secondary-body" color="text-03">
          {fileName}
        </Text>
      )}
    </InputVertical>
  );
}
