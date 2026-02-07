"use client";

import { useState, ReactNode } from "react";
import useSWR, { useSWRConfig, KeyedMutator } from "swr";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "../../interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SvgArrowExchange, SvgSettings } from "@opal/icons";
import { Card } from "@/refresh-components/cards";
import * as GeneralLayouts from "@/layouts/general-layouts";
import { ProviderIcon } from "../../ProviderIcon";
import IconButton from "@/refresh-components/buttons/IconButton";
import LineItem from "@/refresh-components/buttons/LineItem";
import LLMFormLayout from "./FormLayout";

export interface ProviderFormContext {
  onClose: () => void;
  mutate: KeyedMutator<any>;
  popup: ReactNode;
  setPopup: (popup: PopupSpec) => void;
  isTesting: boolean;
  setIsTesting: (testing: boolean) => void;
  testError: string;
  setTestError: (error: string) => void;
  wellKnownLLMProvider: WellKnownLLMProviderDescriptor | undefined;
}

interface ProviderFormEntrypointWrapperProps {
  children: (context: ProviderFormContext) => ReactNode;
  providerName: string;
  providerDisplayName?: string;
  providerInternalName?: string;
  providerEndpoint?: string;
  existingLlmProvider?: LLMProviderView;
}

export function ProviderFormEntrypointWrapper({
  children,
  providerName,
  providerDisplayName,
  providerInternalName,
  providerEndpoint,
  existingLlmProvider,
}: ProviderFormEntrypointWrapperProps) {
  const [formIsVisible, setFormIsVisible] = useState(false);

  // Shared hooks
  const { mutate } = useSWRConfig();
  const { popup, setPopup } = usePopup();

  // Shared state for testing
  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  // Fetch model configurations for this provider
  const { data: wellKnownLLMProvider } = useSWR<WellKnownLLMProviderDescriptor>(
    providerEndpoint
      ? `/api/admin/llm/built-in/options/${providerEndpoint}`
      : null,
    errorHandlingFetcher
  );

  const onClose = () => setFormIsVisible(false);

  const context: ProviderFormContext = {
    onClose,
    mutate,
    popup,
    setPopup,
    isTesting,
    setIsTesting,
    testError,
    setTestError,
    wellKnownLLMProvider,
  };

  const displayName = providerDisplayName ?? providerName;
  const internalName = providerInternalName ?? providerName;

  return (
    <>
      {popup}
      <Card padding={0}>
        {existingLlmProvider ? (
          <GeneralLayouts.CardItemLayout
            icon={() => <ProviderIcon provider={internalName} size={24} />}
            title={displayName}
            description={providerName}
            rightChildren={
              <IconButton
                icon={SvgSettings}
                internal
                onClick={() => setFormIsVisible(true)}
              />
            }
          />
        ) : (
          <GeneralLayouts.CardItemLayout
            icon={() => <ProviderIcon provider={internalName} size={24} />}
            title={displayName}
            description={providerName}
            rightChildren={
              <LineItem
                children="Connect"
                icon={SvgArrowExchange}
                onClick={() => setFormIsVisible(true)}
              />
            }
          />
        )}
      </Card>

      {formIsVisible && (
        <LLMFormLayout.Modal
          icon={() => <ProviderIcon provider={internalName} size={24} />}
          displayName={displayName}
          onClose={onClose}
        >
          {children(context)}
        </LLMFormLayout.Modal>
      )}
    </>
  );
}
