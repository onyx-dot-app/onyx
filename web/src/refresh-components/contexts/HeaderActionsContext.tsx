"use client";

import React, {
  ReactNode,
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
} from "react";

interface HeaderActionsState {
  node: ReactNode | null;
  reserveSpace: boolean;
}

interface HeaderActionsContextValue extends HeaderActionsState {
  setHeaderActions: (node: ReactNode | null) => void;
  reserveHeaderSpace: () => void;
  clearHeaderActions: () => void;
}

const HeaderActionsContext = createContext<HeaderActionsContextValue | null>(
  null
);

export function HeaderActionsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [state, setState] = useState<HeaderActionsState>({
    node: null,
    reserveSpace: false,
  });

  const setHeaderActions = useCallback<
    HeaderActionsContextValue["setHeaderActions"]
  >((node) => {
    setState((prev) => ({
      ...prev,
      node,
    }));
  }, []);

  const reserveHeaderSpace = useCallback(() => {
    setState((prev) => ({
      ...prev,
      reserveSpace: true,
    }));
  }, []);

  const clearHeaderActions = useCallback(() => {
    setState({
      node: null,
      reserveSpace: false,
    });
  }, []);

  const value = useMemo<HeaderActionsContextValue>(
    () => ({
      ...state,
      setHeaderActions,
      reserveHeaderSpace,
      clearHeaderActions,
    }),
    [state, setHeaderActions, reserveHeaderSpace, clearHeaderActions]
  );

  return (
    <HeaderActionsContext.Provider value={value}>
      {children}
    </HeaderActionsContext.Provider>
  );
}

export function useHeaderActions() {
  const context = useContext(HeaderActionsContext);
  if (!context) {
    throw new Error(
      "useHeaderActions must be used within a HeaderActionsProvider"
    );
  }

  return {
    setHeaderActions: context.setHeaderActions,
    reserveHeaderSpace: context.reserveHeaderSpace,
    clearHeaderActions: context.clearHeaderActions,
  };
}

export function useHeaderActionsValue() {
  const context = useContext(HeaderActionsContext);
  if (!context) {
    throw new Error(
      "useHeaderActionsValue must be used within a HeaderActionsProvider"
    );
  }

  return {
    headerNode: context.node,
    reserveSpace: context.reserveSpace,
  };
}
