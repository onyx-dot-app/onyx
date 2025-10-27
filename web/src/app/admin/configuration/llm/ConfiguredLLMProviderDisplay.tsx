import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { LLMProviderView, WellKnownLLMProviderDescriptor } from "./interfaces";
import { Modal } from "@/components/Modal";
import { LLMProviderUpdateForm } from "./LLMProviderUpdateForm";
import { CustomLLMProviderUpdateForm } from "./CustomLLMProviderUpdateForm";
import { useState } from "react";
import { LLM_PROVIDERS_ADMIN_URL } from "./constants";
import { mutate } from "swr";
import { Badge } from "@/components/ui/badge";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { cn, isSubset } from "@/lib/utils";

function LLMProviderUpdateModal({
  llmProviderDescriptor,
  onClose,
  existingLlmProvider,
  shouldMarkAsDefault,
  setPopup,
}: {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor | null | undefined;
  onClose: () => void;
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const providerName = existingLlmProvider?.name
    ? `"${existingLlmProvider.name}"`
    : llmProviderDescriptor?.display_name ||
      llmProviderDescriptor?.name ||
      "Custom LLM Provider";

  return (
    <Modal
      title={`${llmProviderDescriptor ? "Configure" : "Setup"} ${providerName}`}
      onOutsideClick={() => onClose()}
      hideOverflow={true}
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
  existingLlmProvider: LLMProviderView;
  shouldMarkAsDefault?: boolean;
}) {
  const [formIsVisible, setFormIsVisible] = useState(false);
  const { popup, setPopup } = usePopup();

  async function handleSetAsDefault(): Promise<void> {
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

    await mutate(LLM_PROVIDERS_ADMIN_URL);
    setPopup({
      type: "success",
      message: "Provider set as default successfully!",
    });
  }

  const providerName =
    existingLlmProvider?.name ||
    llmProviderDescriptor?.display_name ||
    llmProviderDescriptor?.name;
  return (
    <div>
      {popup}
      <div className="border p-3 bg-background-neutral-01 rounded-16 w-96 flex shadow-md">
        <div className="my-auto">
          <Text headingH3 text04>
            {providerName}{" "}
          </Text>
          <Text secondaryBody text03 className="italic">
            ({existingLlmProvider.provider})
          </Text>
          {!existingLlmProvider.is_default_provider && (
            <Text
              className={cn("text-action-link-05", "cursor-pointer")}
              onClick={handleSetAsDefault}
            >
              Set as default
            </Text>
          )}
        </div>

        {existingLlmProvider && (
          <div className="my-auto ml-3">
            {existingLlmProvider.is_default_provider ? (
              <Badge variant="agent">Default</Badge>
            ) : (
              <Badge variant="success">Enabled</Badge>
            )}
          </div>
        )}

        <div className="ml-auto">
          <Button
            action={!existingLlmProvider}
            secondary={!!existingLlmProvider}
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
  existingLlmProviders: LLMProviderView[];
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
              defaultProviderDesciptor &&
              (defaultProviderDesciptor.model_configurations.length === 0 ||
                isSubset(
                  defaultProviderDesciptor.model_configurations.map(
                    (model_configuration) => model_configuration.name
                  ),
                  provider.model_configurations.map(
                    (model_configuration) => model_configuration.name
                  )
                ))
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
