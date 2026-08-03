"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

type Navigate = () => void;
type NavigationGuard = (navigate: Navigate) => void;

interface UnsavedChangesNavigationContextValue {
  registerGuard: (guard: NavigationGuard) => () => void;
  requestNavigation: NavigationGuard;
}

const UnsavedChangesNavigationContext =
  createContext<UnsavedChangesNavigationContextValue>({
    registerGuard: () => () => undefined,
    requestNavigation: (navigate) => navigate(),
  });

export function UnsavedChangesNavigationProvider({
  children,
}: {
  children: ReactNode;
}) {
  const guards = useRef(new Map<symbol, NavigationGuard>());

  const registerGuard = useCallback((guard: NavigationGuard) => {
    const id = Symbol();
    guards.current.set(id, guard);
    return () => {
      guards.current.delete(id);
    };
  }, []);

  const requestNavigation = useCallback((navigate: Navigate) => {
    const activeGuard = Array.from(guards.current.values()).at(-1);
    if (activeGuard) activeGuard(navigate);
    else navigate();
  }, []);

  const value = useMemo(
    () => ({ registerGuard, requestNavigation }),
    [registerGuard, requestNavigation]
  );

  return (
    <UnsavedChangesNavigationContext.Provider value={value}>
      {children}
    </UnsavedChangesNavigationContext.Provider>
  );
}

export function useUnsavedChangesNavigation() {
  return useContext(UnsavedChangesNavigationContext);
}
