"use client";

import { Modal } from "@/components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";
import useSWR, { mutate } from "swr";
import { Badge, Button, Text, Title } from "@tremor/react";
import { ThreeDotsLoader } from "@/components/Loading";
import { FullLLMProvider, WellKnownLLMProviderDescriptor } from "./interfaces";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { LLMProviderUpdateForm } from "./LLMProviderUpdateForm";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { CustomLLMProviderUpdateForm } from "./CustomLLMProviderUpdateForm";

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

function LLMProviderDisplay({
  llmProviderDescriptor,
  existingLlmProvider,
  shouldMarkAsDefault,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null;
  existingLlmProvider?: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
}) {
  const [formIsVisible, setFormIsVisible] = useState(false);
  const { popup, setPopup } = usePopup();

  const providerName =
    llmProviderDescriptor?.display_name ||
    llmProviderDescriptor?.name ||
    existingLlmProvider?.name;
  return (
    <div>
      {popup}
      <div className="border border-border p-3 rounded w-96 flex shadow-md">
        <div className="my-auto">
          <div className="font-bold">{providerName} </div>
          {existingLlmProvider && !existingLlmProvider.is_default_provider && (
            <div
              className="text-xs text-link cursor-pointer"
              onClick={async () => {
                const response = await fetch(
                  `${LLM_PROVIDERS_ADMIN_URL}/${existingLlmProvider.id}/default`,
                  {
                    method: "POST",
                  }
                );
                if (!response.ok) {
                  const errorMsg = (await response.json()).detail;
                  setPopup({
                    type: "error",
                    message: `Failed to set provider as default: ${errorMsg}`,
                  });
                  return;
                }

                mutate(LLM_PROVIDERS_ADMIN_URL);
                setPopup({
                  type: "success",
                  message: "Provider set as default successfully!",
                });
              }}
            >
              Set as default
            </div>
          )}
        </div>

        {existingLlmProvider && (
          <div className="my-auto">
            {existingLlmProvider.is_default_provider ? (
              <Badge color="orange" className="ml-2" size="xs">
                Default
              </Badge>
            ) : (
              <Badge color="green" className="ml-2" size="xs">
                Enabled
              </Badge>
            )}
          </div>
        )}

        <div className="ml-auto">
          <Button
            color={existingLlmProvider ? "green" : "blue"}
            size="xs"
            onClick={() => setFormIsVisible(true)}
          >
            {existingLlmProvider ? "Edit" : "Set up"}
          </Button>
        </div>
      </div>
      {formIsVisible && (
        <LLMProviderUpdateModal
          llmProviderDescriptor={llmProviderDescriptor}
          onClose={() => setFormIsVisible(false)}
          existingLlmProvider={existingLlmProvider}
          shouldMarkAsDefault={shouldMarkAsDefault}
          setPopup={setPopup}
        />
      )}
    </div>
  );
}

function AddCustomLLMProvider({}) {
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

  const wellKnownLLMProviderNames = llmProviderDescriptors.map(
    (llmProviderDescriptor) => llmProviderDescriptor.name
  );
  const customLLMProviders = existingLlmProviders.filter(
    (llmProvider) => !wellKnownLLMProviderNames.includes(llmProvider.name)
  );

  return (
    <>
      <Text className="mb-4">
        If multiple LLM providers are enabled, the default provider will be used
        for all &quot;Default&quot; Personas. For user-created Personas, you can
        select the LLM provider/model that best fits the use case!
      </Text>

      <Title className="mb-2">Default Providers</Title>
      <div className="gap-y-4 flex flex-col">
        {llmProviderDescriptors.map((llmProviderDescriptor) => {
          const existingLlmProvider = existingLlmProviders.find(
            (llmProvider) => llmProvider.name === llmProviderDescriptor.name
          );

          return (
            <LLMProviderDisplay
              key={llmProviderDescriptor.name}
              llmProviderDescriptor={llmProviderDescriptor}
              existingLlmProvider={existingLlmProvider}
              shouldMarkAsDefault={existingLlmProviders.length === 0}
            />
          );
        })}
      </div>

      <Title className="mb-2 mt-4">Custom Providers</Title>
      {customLLMProviders.length > 0 && (
        <div className="gap-y-4 flex flex-col mb-4">
          {customLLMProviders.map((llmProvider) => (
            <LLMProviderDisplay
              key={llmProvider.id}
              llmProviderDescriptor={null}
              existingLlmProvider={llmProvider}
            />
          ))}
        </div>
      )}

      <AddCustomLLMProvider />
    </>
  );
}
