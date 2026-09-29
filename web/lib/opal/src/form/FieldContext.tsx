"use client";

import { createContext, useContext } from "react";

export type FormFieldState = "idle" | "success" | "error";

export interface FieldContextType {
  baseId: string;
  name?: string;
  required?: boolean;
  state: FormFieldState;
  describedByIds: string[];
}

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
