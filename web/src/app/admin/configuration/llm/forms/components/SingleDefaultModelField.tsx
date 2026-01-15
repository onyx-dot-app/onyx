import { TextFormField } from "@/components/Field";

interface SingleDefaultModelFieldProps {
  placeholder?: string;
}

export function SingleDefaultModelField({
  placeholder = "E.g. gpt-4o",
}: SingleDefaultModelFieldProps) {
  return (
    <TextFormField
      name="default_model_name"
      label="Default Model"
      subtext="The model to use by default for this provider unless otherwise specified."
      placeholder={placeholder}
    />
  );
}
