import { TextFormField } from "@/components/Field";

export function ApiKeyField({ label }: { label?: string }) {
  return (
    <TextFormField
      name="api_key"
      label={label || "API Key"}
      placeholder="API Key"
      type="password"
    />
  );
}
