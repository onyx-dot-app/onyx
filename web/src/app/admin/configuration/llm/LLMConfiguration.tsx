"use client";
import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";

import { Modal } from "@/components/Modal";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useState } from "react";
import useSWR from "swr";
import { Callout } from "@/components/ui/callout";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { Button } from "@/components/ui/button";
import { ThreeDotsLoader } from "@/components/Loading";
import { LLMProviderView, WellKnownLLMProviderDescriptor } from "./interfaces";
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
  existingLlmProvider?: LLMProviderView;
  shouldMarkAsDefault?: boolean;
  setPopup?: (popup: PopupSpec) => void;
}) {
  const { t } = useTranslation();
  const providerName =
    llmProviderDescriptor?.display_name ||
    llmProviderDescriptor?.name ||
    existingLlmProvider?.name ||
    "Custom LLM Provider";

  const hasAdvancedOptions = llmProviderDescriptor?.name != "azure";

  return (
    <Modal
      title={`${t(k.SETUP)} ${providerName}`}
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
            hasAdvancedOptions={hasAdvancedOptions}
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
  const { t } = useTranslation();
  const [formIsVisible, setFormIsVisible] = useState(false);
  const { popup, setPopup } = usePopup();

  const providerName =
    llmProviderDescriptor?.display_name || llmProviderDescriptor?.name;
  return (
    <div>
      {popup}
      <div className="border border-border p-3 dark:bg-neutral-800 dark:border-neutral-700 rounded w-96 flex shadow-md">
        <div className="my-auto">
          <div className="font-bold">{providerName}</div>
        </div>
        <div className="ml-auto">
          <Button variant="navigate" onClick={() => setFormIsVisible(true)}>
            {t(k.SET_UP)}
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
  const { t } = useTranslation();
  const [formIsVisible, setFormIsVisible] = useState(false);

  if (formIsVisible) {
    return (
      <Modal
        title={`${t(k.SETUP_CUSTOM_LLM_PROVIDER)}`}
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
    <Button variant="navigate" onClick={() => setFormIsVisible(true)}>
      {t(k.ADD_CUSTOM_LLM_PROVIDER)}
    </Button>
  );
}

export function LLMConfiguration() {
  const { t } = useTranslation();
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

  return (
    <>
      <Title className="mb-2">{t(k.ENABLED_LLM_PROVIDERS)}</Title>

      {existingLlmProviders.length > 0 ? (
        <>
          <Text className="mb-4">{t(k.IF_MULTIPLE_LLM_PROVIDERS_ARE)}</Text>
          <ConfiguredLLMProviderDisplay
            existingLlmProviders={existingLlmProviders}
            llmProviderDescriptors={llmProviderDescriptors}
          />
        </>
      ) : (
        <Callout type="warning" title={t(k.NO_LLM_PROVIDERS_CONFIGURED)}>
          {t(k.PLEASE_SET_ONE_UP_BELOW_IN_ORD)}
        </Callout>
      )}

      <Title className="mb-2 mt-6">{t(k.ADD_LLM_PROVIDER)}</Title>
      <Text className="mb-4">{t(k.ADD_A_NEW_LLM_PROVIDER_BY_EITH)}</Text>

      <div className="gap-y-4 flex flex-col">
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
      </div>
    </>
  );
}
