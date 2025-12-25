import { createContext, useContext } from "react";
import { FieldContextType } from "./types";
import { useField } from "formik";

export const FieldContext = createContext<FieldContextType | undefined>(
  undefined
);

export const useFieldContext = () => {
  const context = useContext(FieldContext);
  if (context === undefined) {
    throw new Error(
      "useFieldContext must be used within a FieldContextProvider"
    );
  }
  return context;
};

export function useOnChange<T = any>(name: string, f?: (value: T) => void) {
  const [field, , helpers] = useField<T>(name);
  return (value: T) => {
    f?.(value);
    helpers.setTouched(true);
    field.onChange(value);
  };
}
