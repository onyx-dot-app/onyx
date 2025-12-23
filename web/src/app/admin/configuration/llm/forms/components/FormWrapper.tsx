import { useState, ReactNode } from "react";
import useSWR, { useSWRConfig, KeyedMutator } from "swr";
import { PopupSpec, usePopup } from "@/components/admin/connectors/Popup";
import { LLMProviderView, ModelConfiguration } from "../../interfaces";
import { errorHandlingFetcher } from "@/lib/fetcher";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgSettings } from "@opal/icons";

export interface ProviderFormContext {
  onClose: () => void;
  mutate: KeyedMutator<any>;
  popup: ReactNode;
  setPopup: (popup: PopupSpec) => void;
  isTesting: boolean;
  setIsTesting: (testing: boolean) => void;
  testError: string;
  setTestError: (error: string) => void;
  modelConfigurations: ModelConfiguration[];
}

interface ProviderFormEntrypointWrapperProps {
  children: (context: ProviderFormContext) => ReactNode;
  providerName: string;
  providerEndpoint: string;
  existingLlmProvider?: LLMProviderView;
}

export function ProviderFormEntrypointWrapper({
  children,
  providerName,
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
  const { data: _modelConfigurations } = useSWR<ModelConfiguration[]>(
    `/api/admin/llm/built-in/options/${providerEndpoint}`,
    errorHandlingFetcher
  );
  const modelConfigurations = _modelConfigurations ?? [];

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
    modelConfigurations,
  };

  return (
    <div>
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
        <Modal open onOpenChange={onClose}>
          <Modal.Content medium>
            <Modal.Header
              icon={SvgSettings}
              title={`${existingLlmProvider ? "Configure" : "Setup"} ${
                existingLlmProvider?.name
                  ? `"${existingLlmProvider.name}"`
                  : providerName
              }`}
              onClose={onClose}
            />
            <Modal.Body className="max-h-[70vh] overflow-y-auto">
              {children(context)}
            </Modal.Body>
          </Modal.Content>
        </Modal>
      )}
    </div>
  );
}
