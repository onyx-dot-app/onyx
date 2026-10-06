import { InputNumber } from "@opal/components";
import { InputVertical } from "@opal/layouts";
import { FormikField } from "@/refresh-components/form/FormikField";

interface NumberInputProps {
  name: string;
  label: string;
  description?: string;
  optional?: boolean;
  disabled?: boolean;
}

/** A whole-number field. Empty stores `undefined`; -1 is the lowest value. */
export default function NumberInput({
  name,
  label,
  description,
  optional,
  disabled,
}: NumberInputProps) {
  return (
    // The field name ties the label to the input's id and shows the field's
    // Formik error under it.
    <InputVertical
      withLabel={name}
      disabled={disabled}
      title={label}
      description={description}
      suffix={optional ? "optional" : undefined}
    >
      <FormikField<number | undefined>
        name={name}
        render={(field, helper, _meta, status) => (
          <InputNumber
            id={name}
            value={field.value ?? null}
            onChange={(value) => {
              // InputNumber has no blur callback, so touch on change to show
              // the field's validation error.
              void helper.setTouched(true, false);
              void helper.setValue(value ?? undefined);
            }}
            // Some sources take -1 for "no limit", such as a recursion depth.
            min={-1}
            variant={status === "error" ? "error" : "primary"}
            disabled={disabled}
          />
        )}
      />
    </InputVertical>
  );
}
