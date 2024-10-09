import { SubLabel } from "@/components/admin/connectors/Field";
import { Field } from "formik";

export default function NumberInput({
  label,
  optional,
  description,
  name,
  showNeverIfZero,
}: {
  label: string;
  name: string;
  optional?: boolean;
  description?: string;
  showNeverIfZero?: boolean;
}) {
  return (
    <div className="w-full flex flex-col">
      <label className="block text-base font-medium text-text-700 mb-1">
        {label}
        {optional && <span className="text-text-500 ml-1">(optional)</span>}
      </label>
      {description && <SubLabel>{description}</SubLabel>}

      <Field
        type="number"
        name={name}
        min="-1"
        className={`mt-2 block w-full px-3 py-2 
                bg-white border border-gray-300 rounded-md 
                text-sm shadow-sm placeholder-gray-400
                focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500
                disabled:bg-gray-50 disabled:text-gray-500 disabled:border-gray-200 disabled:shadow-none
                invalid:border-pink-500 invalid:text-pink-600
                focus:invalid:border-pink-500 focus:invalid:ring-pink-500`}
      />
    </div>
  );
}
