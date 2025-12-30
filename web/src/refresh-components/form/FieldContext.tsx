"use client";

import { createContext, useContext } from "react";
import { FieldContextType } from "./types";

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
