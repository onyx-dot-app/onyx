"use client";
import {
  WellKnownLLMProviderDescriptor,
  LLMProviderDescriptor,
} from "@/app/admin/configuration/llm/interfaces";
import React, {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
} from "react";
import { useUser } from "@/providers/UserProvider";
import { useLLMProviders } from "@/lib/hooks/useLLMProviders";
import { useLLMProviderOptions } from "@/lib/hooks/useLLMProviderOptions";

interface ProviderContextType {
  shouldShowConfigurationNeeded: boolean;
  providerOptions: WellKnownLLMProviderDescriptor[];
  refreshProviderInfo: () => Promise<void>;
  // Expose configured provider instances for components that need it (e.g., onboarding)
  llmProviders: LLMProviderDescriptor[] | undefined;
  isLoadingProviders: boolean;
  hasProviders: boolean;
}

const ProviderContext = createContext<ProviderContextType | undefined>(
  undefined
);

const DEFAULT_LLM_PROVIDER_TEST_COMPLETE_KEY = "defaultLlmProviderTestComplete";

function checkDefaultLLMProviderTestComplete() {
  if (typeof window === "undefined") return true;
  return (
    localStorage.getItem(DEFAULT_LLM_PROVIDER_TEST_COMPLETE_KEY) === "true"
  );
}

function setDefaultLLMProviderTestComplete() {
  if (typeof window === "undefined") return;
  localStorage.setItem(DEFAULT_LLM_PROVIDER_TEST_COMPLETE_KEY, "true");
}

export function ProviderContextProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = useUser();

  // Use SWR hooks instead of raw fetch
  const {
    llmProviders,
    isLoading: isLoadingProviders,
    refetch: refetchProviders,
  } = useLLMProviders();
  const { llmProviderOptions: providerOptions, refetch: refetchOptions } =
    useLLMProviderOptions();

  const [defaultCheckSuccessful, setDefaultCheckSuccessful] =
    useState<boolean>(true);

  // Only test default provider once per session
  useEffect(() => {
    const shouldCheck =
      !checkDefaultLLMProviderTestComplete() &&
      (!user || user.role === "admin");

    if (shouldCheck) {
      fetch("/api/admin/llm/test/default", { method: "POST" })
        .then((response) => {
          const success = response?.ok || false;
          setDefaultCheckSuccessful(success);
          if (success) {
            setDefaultLLMProviderTestComplete();
          }
        })
        .catch(() => {
          setDefaultCheckSuccessful(false);
        });
    }
  }, [user]);

  const hasProviders = (llmProviders?.length ?? 0) > 0;
  const validProviderExists = hasProviders && defaultCheckSuccessful;

  const shouldShowConfigurationNeeded =
    !validProviderExists && (providerOptions?.length ?? 0) > 0;

  const refreshProviderInfo = useCallback(async () => {
    await Promise.all([refetchProviders(), refetchOptions()]);
  }, [refetchProviders, refetchOptions]);

  return (
    <ProviderContext.Provider
      value={{
        shouldShowConfigurationNeeded,
        providerOptions: providerOptions ?? [],
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
