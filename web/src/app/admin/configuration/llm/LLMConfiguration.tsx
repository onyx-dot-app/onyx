"use client";

import Modal from "@/refresh-components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";
import useSWR from "swr";
import { Callout } from "@/components/ui/callout";
import Text from "@/refresh-components/texts/Text";
import Title from "@/components/ui/title";
import Button from "@/refresh-components/buttons/Button";
import { ThreeDotsLoader } from "@/components/Loading";
import { LLMProviderView, WellKnownLLMProviderDescriptor } from "./interfaces";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { LLMProviderUpdateForm } from "./LLMProviderUpdateForm";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { CustomLLMProviderUpdateForm } from "./CustomLLMProviderUpdateForm";
import { ConfiguredLLMProviderDisplay } from "./ConfiguredLLMProviderDisplay";
import { SvgSettings } from "@opal/icons";
import { OpenAIForm, OPENAI_PROVIDER_NAME } from "./forms/OpenAIForm";
import { AnthropicForm } from "./forms/AnthropicForm";
import { OllamaForm } from "./forms/OllamaForm";

function LLMProviderUpdateModal({
  llmProviderDescriptor,
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null;
  onClose: () => void;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const providerName =
    llmProviderDescriptor?.display_name ||
    llmProviderDescriptor?.name ||
    existingLlmProvider?.name ||
    "Custom LLM Provider";

  return (
    <Modal open onOpenChange={onClose}>
      <Modal.Content medium>
        <Modal.Header
          icon={SvgSettings}
          title={`Setup ${providerName}`}
          onClose={onClose}
        />
        <Modal.Body className="max-h-[70vh] overflow-y-auto">
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
        </Modal.Body>
      </Modal.Content>
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
      <div className="border p-3 bg-background-neutral-01 rounded-16 w-96 flex shadow-md">
        <div className="my-auto">
          <Text headingH3>{providerName}</Text>
        </div>
        <div className="ml-auto">
          <Button action onClick={() => setFormIsVisible(true)}>
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
  existingLlmProviders: LLMProviderView[];
}) {
  const [formIsVisible, setFormIsVisible] = useState(false);
  const { popup, setPopup } = usePopup();

  if (formIsVisible) {
    return (
      <>
        {popup}
        <Modal open onOpenChange={() => setFormIsVisible(false)}>
          <Modal.Content medium>
            <Modal.Header
              icon={SvgSettings}
              title="Setup Custom LLM Provider"
              onClose={() => setFormIsVisible(false)}
            />
            <Modal.Body className="max-h-[70vh] overflow-y-auto">
              <CustomLLMProviderUpdateForm
                onClose={() => setFormIsVisible(false)}
                shouldMarkAsDefault={existingLlmProviders.length === 0}
                setPopup={setPopup}
              />
            </Modal.Body>
          </Modal.Content>
        </Modal>
      </>
    );
  }

  return (
    <Button action onClick={() => setFormIsVisible(true)}>
      Add Custom LLM Provider
    </Button>
  );
}

export function LLMConfiguration() {
  const { data: llmProviderDescriptors } = useSWR<
    WellKnownLLMProviderDescriptor[]
  >("/api/admin/llm/built-in/options", errorHandlingFetcher);
  const { data: existingLlmProviders } = useSWR<LLMProviderView[]>(
    LLM_PROVIDERS_ADMIN_URL,
    errorHandlingFetcher
  );

  if (!llmProviderDescriptors || !existingLlmProviders) {
    return <ThreeDotsLoader />;
  }

  const isFirstProvider = existingLlmProviders.length === 0;

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
        <Callout type="warning" title="No LLM providers configured yet">
          Please set one up below in order to start using Onyx!
        </Callout>
      )}

      <Title className="mb-2 mt-6">Add LLM Provider</Title>
      <Text className="mb-4">
        Add a new LLM provider by either selecting from one of the default
        providers or by specifying your own custom LLM provider.
      </Text>

      <div className="flex flex-col gap-y-4">
        <OpenAIForm shouldMarkAsDefault={isFirstProvider} />
        <AnthropicForm shouldMarkAsDefault={isFirstProvider} />
        <OllamaForm shouldMarkAsDefault={isFirstProvider} />

        <AddCustomLLMProvider existingLlmProviders={existingLlmProviders} />
      </div>

      {/* <div className="gap-y-4 flex flex-col">
        {llmProviderDescriptors.map((llmProviderDescriptor) => (
          <DefaultLLMProviderDisplay
            key={llmProviderDescriptor.name}
            llmProviderDescriptor={llmProviderDescriptor}
            shouldMarkAsDefault={existingLlmProviders.length === 0}
          />
        ))}
      </div>

      <div className="mt-4">
        <AddCustomLLMProvider existingLlmProviders={existingLlmProviders} />
      </div> */}
    </>
  );
}
