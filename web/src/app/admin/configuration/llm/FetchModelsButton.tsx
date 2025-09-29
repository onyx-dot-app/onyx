import { Button } from "@/components/ui/button";
import { LoadingAnimation } from "@/components/Loading";
import Text from "@/components/ui/text";
import { fetchModels } from "./utils";
import { WellKnownLLMProviderDescriptor, LLMProviderView } from "./interfaces";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface FetchModelsButtonProps {
  llmProviderDescriptor: WellKnownLLMProviderDescriptor;
  existingLlmProvider?: LLMProviderView;
  values: any;
  setFieldValue: any;
  isFetchingModels: boolean;
  setIsFetchingModels: (loading: boolean) => void;
  fetchModelsError: string;
  setFetchModelsError: (error: string) => void;
  setPopup?: (popup: PopupSpec) => void;
}

interface ProviderConfig {
  buttonText: string;
  loadingText: string;
  helperText: string | React.ReactNode;
  isDisabled: (values: any) => boolean;
}

const providerConfigs: Record<string, ProviderConfig> = {
  bedrock: {
    buttonText: "Fetch Available Models for Region",
    loadingText: "Fetching Models...",
    helperText: (
      <>
        Enter your AWS region, then click this button to fetch available Bedrock
        models.
        <br />
        If you&apos;re updating your existing provider, you&apos;ll need to
        click this button to fetch the latest models.
      </>
    ),
    isDisabled: (values) => !values.custom_config?.AWS_REGION_NAME,
  },
  ollama: {
    buttonText: "Fetch Available Ollama Models",
    loadingText: "Fetching Models...",
    helperText: (
      <>
        Ensure your Ollama server is accessible from Onyx and that the requested
        models are pulled (e.g. via <code>ollama pull</code>). Provide the
        server&apos;s base URL and optional API key (when using Ollama Cloud)
        before fetching the available models.
      </>
    ),
    isDisabled: (values) => !values.api_base,
  },
};

export function FetchModelsButton({
  llmProviderDescriptor,
  existingLlmProvider,
  values,
  setFieldValue,
  isFetchingModels,
  setIsFetchingModels,
  fetchModelsError,
  setFetchModelsError,
  setPopup,
}: FetchModelsButtonProps) {
  const config = providerConfigs[llmProviderDescriptor.name];

  // Only render if the provider supports model fetching
  if (!config) {
    return null;
  }

  const handleFetchModels = () => {
    fetchModels(
      llmProviderDescriptor,
      existingLlmProvider,
      values,
      setFieldValue,
      setIsFetchingModels,
      setFetchModelsError,
      setPopup
    );
  };

  return (
    <div className="flex flex-col gap-2">
      <Button
        type="button"
        onClick={handleFetchModels}
        disabled={isFetchingModels || config.isDisabled(values)}
        className="w-fit"
      >
        {isFetchingModels ? (
          <>
            <LoadingAnimation size="text-sm" />
            <span className="ml-2">{config.loadingText}</span>
          </>
        ) : (
          config.buttonText
        )}
      </Button>

      {fetchModelsError && (
        <Text className="text-red-600 text-sm">{fetchModelsError}</Text>
      )}

      <Text className="text-sm text-gray-600">{config.helperText}</Text>
    </div>
  );
}
