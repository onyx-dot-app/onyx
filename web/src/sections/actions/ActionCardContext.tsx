"use client";

import { createContext, ReactNode, useContext } from "react";

export interface ActionCardContextValue {
  isHovered: boolean;
}

const defaultValue: ActionCardContextValue = {
  isHovered: false,
};

const ActionCardContext = createContext<ActionCardContextValue>(defaultValue);

interface ActionCardProviderProps {
  value: ActionCardContextValue;
  children: ReactNode;
}

export function ActionCardProvider({
  value,
  children,
}: ActionCardProviderProps) {
  return (
    <ActionCardContext.Provider value={value}>
      {children}
    </ActionCardContext.Provider>
  );
}

export function useActionCardContext() {
  return useContext(ActionCardContext);
}
