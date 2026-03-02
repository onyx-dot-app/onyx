"use client";

import { useState, ReactNode } from "react";
import useSWR, { useSWRConfig, KeyedMutator } from "swr";
import { toast } from "@/hooks/useToast";
import {
  LLMProviderView,
  WellKnownLLMProviderDescriptor,
} from "@/interfaces/llm";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgSettings } from "@opal/icons";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { LLM_PROVIDERS_ADMIN_URL } from "@/lib/llmConfig/constants";
import { setDefaultLlmModel } from "@/lib/llmConfig/svc";

export interface ProviderFormContext {
  onClose: () => void;
  mutate: KeyedMutator<any>;
  isTesting: boolean;
  setIsTesting: (testing: boolean) => void;
  testError: string;
  setTestError: (error: string) => void;
  wellKnownLLMProvider: WellKnownLLMProviderDescriptor | undefined;
}

interface ProviderFormEntrypointWrapperProps {
  children: (context: ProviderFormContext) => ReactNode;
  providerName: string;
  providerEndpoint?: string;
  existingLlmProvider?: LLMProviderView;
  /** When true, renders a simple button instead of a card-based UI */
  buttonMode?: boolean;
  /** Custom button text for buttonMode (defaults to "Add {providerName}") */
  buttonText?: string;
  /** Controlled open state — when defined, the wrapper renders only a modal (no card/button UI) */
  open?: boolean;
  /** Callback when controlled modal requests close */
  onOpenChange?: (open: boolean) => void;
}

export function ProviderFormEntrypointWrapper({
  children,
  providerName,
  providerEndpoint,
  existingLlmProvider,
  buttonMode,
  buttonText,
  open,
  onOpenChange,
}: ProviderFormEntrypointWrapperProps) {
  const [formIsVisible, setFormIsVisible] = useState(false);
  const isControlled = open !== undefined;

  // Shared hooks
  const { mutate } = useSWRConfig();

  // Shared state for testing
  const [isTesting, setIsTesting] = useState(false);
  const [testError, setTestError] = useState<string>("");

  // Suppress SWR when controlled + closed to avoid unnecessary API calls
  const swrKey =
    providerEndpoint && !(isControlled && !open)
      ? `/api/admin/llm/built-in/options/${providerEndpoint}`
      : null;

  // Fetch model configurations for this provider
  const { data: wellKnownLLMProvider } = useSWR<WellKnownLLMProviderDescriptor>(
    swrKey,
    errorHandlingFetcher
  );

  const onClose = () => {
    if (isControlled) {
      onOpenChange?.(false);
    } else {
      setFormIsVisible(false);
    }
  };

  async function handleSetAsDefault(): Promise<void> {
    if (!existingLlmProvider) return;

    const firstVisibleModel = existingLlmProvider.model_configurations.find(
      (m) => m.is_visible
    );
    if (!firstVisibleModel) {
      toast.error("No visible models available for this provider.");
      return;
    }

    try {
      await setDefaultLlmModel(existingLlmProvider.id, firstVisibleModel.name);
      await mutate(LLM_PROVIDERS_ADMIN_URL);
      toast.success("Provider set as default successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to set provider as default: ${message}`);
    }
  }

  const context: ProviderFormContext = {
    onClose,
    mutate,
    isTesting,
    setIsTesting,
    testError,
    setTestError,
    wellKnownLLMProvider,
  };

  const defaultTitle = `${existingLlmProvider ? "Configure" : "Setup"} ${
    existingLlmProvider?.name ? `"${existingLlmProvider.name}"` : providerName
  }`;

  function renderModal(isVisible: boolean, title?: string) {
    if (!isVisible) return null;
    return (
      <Modal open onOpenChange={onClose}>
        <Modal.Content>
          <Modal.Header
            icon={SvgSettings}
            title={title ?? defaultTitle}
            onClose={onClose}
          />
          <Modal.Body>{children(context)}</Modal.Body>
        </Modal.Content>
      </Modal>
    );
  }

  // Controlled mode: render nothing when closed, render only modal when open
  if (isControlled) {
    return renderModal(!!open);
  }

  // Button mode: simple button that opens a modal
  if (buttonMode && !existingLlmProvider) {
    return (
      <>
        <Button action onClick={() => setFormIsVisible(true)}>
          {buttonText ?? `Add ${providerName}`}
        </Button>
        {renderModal(formIsVisible, `Setup ${providerName}`)}
      </>
    );
  }

  // Card mode: card-based UI with modal
  return (
    <div>
      <div className="border p-3 bg-background-neutral-01 rounded-16 w-96 flex shadow-md">
        {existingLlmProvider ? (
          <>
            <div className="my-auto">
              <Text
                as="p"
                headingH3
                text04
                className="text-ellipsis overflow-hidden max-w-32"
              >
                {existingLlmProvider.name}
              </Text>
              <Text as="p" secondaryBody text03 className="italic">
                ({providerName})
              </Text>
              <Text
                as="p"
                className={cn("text-action-link-05", "cursor-pointer")}
                onClick={handleSetAsDefault}
              >
                Set as default
              </Text>
            </div>

            {existingLlmProvider && (
              <div className="my-auto ml-3">
                <Badge variant="success">Enabled</Badge>
              </div>
            )}

            <div className="ml-auto my-auto">
              <Button
                action={!existingLlmProvider}
                secondary={!!existingLlmProvider}
                onClick={() => setFormIsVisible(true)}
              >
                Edit
              </Button>
            </div>
          </>
        ) : (
          <>
            <div className="my-auto">
              <Text as="p" headingH3>
                {providerName}
              </Text>
            </div>
            <div className="ml-auto my-auto">
              <Button action onClick={() => setFormIsVisible(true)}>
                Set up
              </Button>
            </div>
          </>
        )}
      </div>

      {renderModal(formIsVisible)}
    </div>
  );
}
