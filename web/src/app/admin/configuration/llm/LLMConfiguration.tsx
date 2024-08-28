"use client";

import { Modal } from "@/components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";
import useSWR from "swr";
import { Button, Callout, Text, Title } from "@tremor/react";
import { ThreeDotsLoader } from "@/components/Loading";
import { FullLLMProvider, WellKnownLLMProviderDescriptor } from "./interfaces";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { LLMProviderUpdateForm } from "./LLMProviderUpdateForm";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { CustomLLMProviderUpdateForm } from "./CustomLLMProviderUpdateForm";
import { ConfiguredLLMProviderDisplay } from "./ConfiguredLLMProviderDisplay";

function LLMProviderUpdateModal({
  llmProviderDescriptor,
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null;
  onClose: () => void;
  existingLlmProvider?: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const providerName =
    llmProviderDescriptor?.display_name ||
    llmProviderDescriptor?.name ||
    existingLlmProvider?.name ||
    "Custom LLM Provider";
  return (
    <Modal title={`Setup ${providerName}`} onOutsideClick={() => onClose()}>
      <div className="max-h-[70vh] overflow-y-auto px-4">
        {llmProviderDescriptor ? (
          <LLMProviderUpdateForm
            llmProviderDescriptor={llmProviderDescriptor}
            onClose={onClose}
            existingLlmProvider={existingLlmProvider}
            shouldMarkAsDefault={shouldMarkAsDefault}
            setPopup={setPopup}
          />
        ) : (
          <CustomLLMProviderUpdateForm
            onClose={onClose}
            existingLlmProvider={existingLlmProvider}
            shouldMarkAsDefault={shouldMarkAsDefault}
            setPopup={setPopup}
          />
        )}
      </div>
    </Modal>
  );
}

function DefaultLLMProviderDisplay({
  llmProviderDescriptor,
  shouldMarkAsDefault,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null;
  shouldMarkAsDefault?: boolean;
}) {
  const [formIsVisible, setFormIsVisible] = useState(false);
  const { popup, setPopup } = usePopup();

  const providerName =
    llmProviderDescriptor?.display_name || llmProviderDescriptor?.name;
  return (
    <div>
      {popup}
      <div className="border border-border p-3 rounded w-96 flex shadow-md">
        <div className="my-auto">
          <div className="font-bold">{providerName} </div>
        </div>

        <div className="ml-auto">
          <Button color="blue" size="xs" onClick={() => setFormIsVisible(true)}>
            Set up
          </Button>
        </div>
      </div>
      {formIsVisible && (
        <LLMProviderUpdateModal
          llmProviderDescriptor={llmProviderDescriptor}
          onClose={() => setFormIsVisible(false)}
          shouldMarkAsDefault={shouldMarkAsDefault}
          setPopup={setPopup}
        />
      )}
    </div>
  );
}

function AddCustomLLMProvider({
  existingLlmProviders,
}: {
  existingLlmProviders: FullLLMProvider[];
}) {
  const [formIsVisible, setFormIsVisible] = useState(false);

  if (formIsVisible) {
    return (
      <Modal
        title={`Setup Custom LLM Provider`}
        onOutsideClick={() => setFormIsVisible(false)}
      >
        <div className="max-h-[70vh] overflow-y-auto px-4">
          <CustomLLMProviderUpdateForm
            onClose={() => setFormIsVisible(false)}
            shouldMarkAsDefault={existingLlmProviders.length === 0}
          />
        </div>
      </Modal>
    );
  }

  return (
    <Button size="xs" onClick={() => setFormIsVisible(true)}>
      Add Custom LLM Provider
    </Button>
  );
}

export function LLMConfiguration() {
  const { data: llmProviderDescriptors } = useSWR<
    WellKnownLLMProviderDescriptor[]
  >("/api/admin/llm/built-in/options", errorHandlingFetcher);
  const { data: existingLlmProviders } = useSWR<FullLLMProvider[]>(
    LLM_PROVIDERS_ADMIN_URL,
    errorHandlingFetcher
  );

  if (!llmProviderDescriptors || !existingLlmProviders) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      <Title className="mb-2">Enabled LLM Providers</Title>

      {existingLlmProviders.length > 0 ? (
        <>
          <Text className="mb-4">
            If multiple LLM providers are enabled, the default provider will be
            used for all &quot;Default&quot; Assistants. For user-created
            Assistants, you can select the LLM provider/model that best fits the
            use case!
          </Text>
          <ConfiguredLLMProviderDisplay
            existingLlmProviders={existingLlmProviders}
            llmProviderDescriptors={llmProviderDescriptors}
          />
        </>
      ) : (
        <Callout title="No LLM providers configured yet" color="yellow">
          Please set one up below in order to start using Danswer!
        </Callout>
      )}

      <Title className="mb-2 mt-6">Add LLM Provider</Title>
      <Text className="mb-4">
        Add a new LLM provider by either selecting from one of the default
        providers or by specifying your own custom LLM provider.
      </Text>

      <div className="gap-y-4 flex flex-col">
        {llmProviderDescriptors.map((llmProviderDescriptor) => {
          return (
            <DefaultLLMProviderDisplay
              key={llmProviderDescriptor.name}
              llmProviderDescriptor={llmProviderDescriptor}
              shouldMarkAsDefault={existingLlmProviders.length === 0}
            />
          );
        })}
      </div>

      <div className="mt-4">
        <AddCustomLLMProvider existingLlmProviders={existingLlmProviders} />
      </div>
    </>
  );
}
