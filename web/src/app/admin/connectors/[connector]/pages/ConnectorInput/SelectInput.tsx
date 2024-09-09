import CredentialSubText from "@/components/credentials/CredentialFields";
import { ListOption, SelectOption } from "@/lib/connectors/connectors";
import { Field } from "formik";

export default function SelectInput({
  field,
  value,
}: {
  field: SelectOption;
  value: any;
}) {
  return (
    <>
      <label
        htmlFor={field.name}
        className="block text-sm font-medium text-text-700 mb-1"
      >
        {field.label}
        {field.optional && (
          <span className="text-text-500 ml-1">(optional)</span>
        )}
      </label>
      {field.description && (
        <CredentialSubText>{field.description}</CredentialSubText>
      )}

      <Field
        as="select"
        value={value}
        name={field.name}
        className="w-full p-2 border bg-input border-border-medium rounded-md bg-black focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
      >
        <option value="">Select an option</option>
        {field.options?.map((option: any) => (
          <option key={option.name} value={option.name}>
            {option.name}
          </option>
        ))}
      </Field>
    </>
  );
}
