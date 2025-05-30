import { Label, SubLabel } from "@/components/Field";
import { ErrorMessage, useField } from "formik";

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
  const [field, meta, helpers] = useField(name);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // If the input is empty, set the value to undefined or null
    // This prevents the "NaN from empty string" error
    if (e.target.value === "") {
      helpers.setValue(undefined);
    } else {
      helpers.setValue(Number(e.target.value));
    }
  };

  return (
    <div className="w-full flex flex-col">
      <Label>
        <>
          {label}
          {optional && <span className="text-text-500 ml-1">(optional)</span>}
        </>
      </Label>
      {description && <SubLabel>{description}</SubLabel>}

      <input
        {...field}
        type="number"
        min="-1"
        onChange={handleChange}
        value={
          field.value === undefined || field.value === null ? "" : field.value
        }
        className={`mt-2 block w-full px-3 py-2 
                bg-[#fff] dark:bg-transparent border border-background-300 rounded-md 
                text-sm shadow-sm placeholder-text-400
                focus:outline-none focus:border-sky-500 focus:ring-1 focus:ring-sky-500
                disabled:bg-background-50 disabled:text-text-500 disabled:border-background-200 disabled:shadow-none
                invalid:border-pink-500 invalid:text-pink-600
                focus:invalid:border-pink-500 focus:invalid:ring-pink-500`}
      />
      <ErrorMessage
        name={name}
        component="div"
        className="text-error text-sm mt-1"
      />
    </div>
  );
}
