import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { FullLLMProvider, WellKnownLLMProviderDescriptor } from "./interfaces";
import { Modal } from "@/components/Modal";
import { LLMProviderUpdateForm } from "./LLMProviderUpdateForm";
import { CustomLLMProviderUpdateForm } from "./CustomLLMProviderUpdateForm";
import { useState } from "react";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { mutate } from "swr";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import isEqual from "lodash/isEqual";

function LLMProviderUpdateModal({
  llmProviderDescriptor,
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null | undefined;
  onClose: () => void;
  existingLlmProvider?: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const providerName = existingLlmProvider?.name
    ? `"${existingLlmProvider.name}"`
    : null ||
      llmProviderDescriptor?.display_name ||
      llmProviderDescriptor?.name ||
      "Custom LLM Provider";
  return (
    <Modal
      title={`${llmProviderDescriptor ? "Configure" : "Setup"} ${providerName}`}
      onOutsideClick={() => onClose()}
    >
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
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null | undefined;
  existingLlmProvider: FullLLMProvider;
  shouldMarkAsDefault?: boolean;
}) {
  const [formIsVisible, setFormIsVisible] = useState(false);
  const { popup, setPopup } = usePopup();

  const providerName =
    existingLlmProvider?.name ||
    llmProviderDescriptor?.display_name ||
    llmProviderDescriptor?.name;
  return (
    <div>
      {popup}
      <div className="border border-border p-3 rounded w-96 flex shadow-md">
        <div className="my-auto">
          <div className="font-bold">{providerName} </div>
          <div className="text-xs italic">({existingLlmProvider.provider})</div>
          {!existingLlmProvider.is_default_provider && (
            <div
              className="text-xs text-link cursor-pointer pt-1"
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
          <div className="my-auto ml-3">
            {existingLlmProvider.is_default_provider ? (
              <Badge variant="orange">Default</Badge>
            ) : (
              <Badge variant="success">Enabled</Badge>
            )}
          </div>
        )}

        <div className="ml-auto">
          <Button
            variant={existingLlmProvider ? "success-reverse" : "navigate"}
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

export function ConfiguredLLMProviderDisplay({
  existingLlmProviders,
  llmProviderDescriptors,
}: {
  existingLlmProviders: FullLLMProvider[];
  llmProviderDescriptors: WellKnownLLMProviderDescriptor[];
}) {
  existingLlmProviders = existingLlmProviders.sort((a, b) => {
    if (a.is_default_provider && !b.is_default_provider) {
      return -1;
    }
    if (!a.is_default_provider && b.is_default_provider) {
      return 1;
    }
    return a.provider > b.provider ? 1 : -1;
  });

  return (
    <div className="gap-y-4 flex flex-col">
      {existingLlmProviders.map((provider) => {
        const defaultProviderDesciptor = llmProviderDescriptors.find(
          (llmProviderDescriptors) =>
            llmProviderDescriptors.name === provider.provider
        );

        return (
          <LLMProviderDisplay
            key={provider.id}
            // if the user has specified custom model names,
            // then the provider is custom - don't use the default
            // provider descriptor
            llmProviderDescriptor={
              isEqual(provider.model_names, defaultProviderDesciptor?.llm_names)
                ? defaultProviderDesciptor
                : null
            }
            existingLlmProvider={provider}
          />
        );
      })}
    </div>
  );
}
