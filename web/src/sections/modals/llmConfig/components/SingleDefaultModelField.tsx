import InputTypeInField from "@/refresh-components/form/InputTypeInField";
import * as InputLayouts from "@/layouts/input-layouts";

interface SingleDefaultModelFieldProps {
  placeholder?: string;
}

export function SingleDefaultModelField({
  placeholder = "E.g. gpt-4o",
}: SingleDefaultModelFieldProps) {
  return (
    <InputLayouts.Vertical
      name="default_model_name"
      title="Default Model"
      description="The model to use by default for this provider unless otherwise specified."
    >
      <InputTypeInField name="default_model_name" placeholder={placeholder} />
    </InputLayouts.Vertical>
  );
}
