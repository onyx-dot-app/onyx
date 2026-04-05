"use client";
import { LLMProviderDescriptor } from "@/interfaces/llm";
import React, { createContext, useContext, useCallback } from "react";
import { useLLMProviders } from "@/hooks/useLLMProviders";

interface ProviderContextType {
  refreshProviderInfo: () => Promise<void>;
  llmProviders: LLMProviderDescriptor[] | undefined;
  isLoadingProviders: boolean;
  hasProviders: boolean;
}

const ProviderContext = createContext<ProviderContextType | undefined>(
  undefined
);

export function ProviderContextProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const {
    llmProviders,
    isLoading: isLoadingProviders,
    refetch: refetchProviders,
  } = useLLMProviders();

  const hasProviders = (llmProviders?.length ?? 0) > 0;

  const refreshProviderInfo = useCallback(async () => {
    await refetchProviders();
  }, [refetchProviders]);

  return (
    <ProviderContext.Provider
      value={{
        refreshProviderInfo,
        llmProviders,
        isLoadingProviders,
        hasProviders,
      }}
    >
      {children}
    </ProviderContext.Provider>
  );
}

export function useProviderStatus() {
  const context = useContext(ProviderContext);
  if (context === undefined) {
    throw new Error(
      "useProviderStatus must be used within a ProviderContextProvider"
    );
  }
  return context;
}
