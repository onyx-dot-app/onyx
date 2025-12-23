import { TextFormField } from "@/components/Field";

export function ApiKeyField() {
  return (
    <TextFormField
      name="api_key"
      label="API Key"
      placeholder="API Key"
      type="password"
    />
  );
}
