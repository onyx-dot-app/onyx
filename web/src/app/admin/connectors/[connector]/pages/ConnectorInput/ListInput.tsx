import CredentialSubText from "@/components/credentials/CredentialFields";
import { TrashIcon } from "@/components/icons/icons";
import { ListOption } from "@/lib/connectors/connectors";
import { Field, FieldArray, useField } from "formik";
import { FaPlus } from "react-icons/fa";

export default function ListInput({
  field,
  onUpdate,
}: {
  field: ListOption;
  onUpdate?: (values: string[]) => void;
}) {
  const [fieldProps, , helpers] = useField(field.name);

  return (
    <FieldArray name={field.name}>
      {({ push, remove }) => (
        <div>
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

          {fieldProps.value.map((value: string, index: number) => (
            <div key={index} className="w-full flex mb-4">
              <Field
                name={`${field.name}.${index}`}
                className="w-full bg-input text-sm p-2 border border-border-medium rounded-md focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 mr-2"
              />
              <button
                className="p-2 my-auto bg-input flex-none rounded-md bg-red-500 text-white hover:bg-red-600 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-opacity-50"
                type="button"
                onClick={() => {
                  remove(index);
                  if (onUpdate) {
                    const newValue = fieldProps.value.filter(
                      (_: any, i: number) => i !== index
                    );
                    onUpdate(newValue);
                  }
                }}
              >
                <TrashIcon className="text-white my-auto" />
              </button>
            </div>
          ))}

          <button
            type="button"
            onClick={() => {
              push("");
              if (onUpdate) {
                onUpdate([...fieldProps.value, ""]);
              }
            }}
            className="mt-2 p-2 bg-rose-500 text-xs text-white rounded-md hover:bg-rose-600 focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-opacity-50 flex items-center"
          >
            <FaPlus className="mr-2" />
            Add {field.label}
          </button>
        </div>
      )}
    </FieldArray>
  );
}
