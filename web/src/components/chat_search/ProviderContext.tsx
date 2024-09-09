"use client";
import { WellKnownLLMProviderDescriptor } from "@/app/admin/configuration/llm/interfaces";
import React, { createContext, useContext, useState, useEffect } from "react";
import { useUser } from "../user/UserProvider";
import { useRouter } from "next/navigation";
import { checkLlmProvider } from "../initialSetup/welcome/lib";

interface ProviderContextType {
  shouldShowConfigurationNeeded: boolean;
  providerOptions: WellKnownLLMProviderDescriptor[];
  refreshProviderInfo: () => Promise<void>; // Add this line
}

const ProviderContext = createContext<ProviderContextType | undefined>(
  undefined
);

export function ProviderContextProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = useUser();
  const router = useRouter();

  const [validProviderExists, setValidProviderExists] = useState<boolean>(true);
  const [providerOptions, setProviderOptions] = useState<
    WellKnownLLMProviderDescriptor[]
  >([]);

  const fetchProviderInfo = async () => {
    const { providers, options, defaultCheckSuccessful } =
      await checkLlmProvider(user);
    setValidProviderExists(providers.length > 0 && defaultCheckSuccessful);
    setProviderOptions(options);
  };

  useEffect(() => {
    fetchProviderInfo();
  }, [router, user]);

  const shouldShowConfigurationNeeded =
    !validProviderExists && providerOptions.length > 0;

  const refreshProviderInfo = async () => {
    await fetchProviderInfo();
  };

  return (
    <ProviderContext.Provider
      value={{
        shouldShowConfigurationNeeded,
        providerOptions,
        refreshProviderInfo, // Add this line
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
