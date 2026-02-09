import { useState, useEffect, useCallback } from "react";
import { VisionProvider } from "@/app/admin/configuration/llm/interfaces";
import {
  fetchVisionProviders,
  setDefaultVisionProvider,
} from "@/lib/llm/visionLLM";
import { parseLlmDescriptor, structureValue } from "@/lib/llm/utils";

// Define a type for the popup setter function
type SetPopup = (popup: {
  message: string;
  type: "success" | "error" | "info";
}) => void;

// Accept the setPopup function as a parameter
export function useVisionProviders(setPopup: SetPopup) {
  const [visionProviders, setVisionProviders] = useState<VisionProvider[]>([]);
  const [visionLLM, setVisionLLM] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadVisionProviders = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchVisionProviders();
      setVisionProviders(data);

      // Find the default vision provider and set it
      const defaultProvider = data.find(
        (provider) => provider.is_default_vision_provider
      );

      if (defaultProvider) {
        const modelToUse =
          defaultProvider.default_vision_model ||
          defaultProvider.default_model_name;

        if (modelToUse && defaultProvider.vision_models.includes(modelToUse)) {
          setVisionLLM(
            structureValue(
              defaultProvider.name,
              defaultProvider.provider,
              modelToUse
            )
          );
        }
      }
    } catch (error) {
      console.error("Error fetching vision providers:", error);
      setError(
        error instanceof Error ? error.message : "Unknown error occurred"
      );
      setPopup({
        message: `Failed to load vision providers: ${
          error instanceof Error ? error.message : "Unknown error"
        }`,
        type: "error",
      });
    } finally {
      setIsLoading(false);
    }
  }, []);

  const updateDefaultVisionProvider = useCallback(
    async (llmValue: string | null) => {
      if (!llmValue) {
        setPopup({
          message: "Please select a valid vision model",
          type: "error",
        });
        return false;
      }

      try {
        const { name, modelName } = parseLlmDescriptor(llmValue);

        // Find the provider ID
        const providerObj = visionProviders.find((p) => p.name === name);
        if (!providerObj) {
          throw new Error("Provider not found");
        }

        await setDefaultVisionProvider(providerObj.id, modelName);

        setPopup({
          message: "Default vision provider updated successfully!",
          type: "success",
        });
        setVisionLLM(llmValue);

        // Refresh the list to reflect the change
        await loadVisionProviders();
        return true;
      } catch (error: unknown) {
        console.error("Error setting default vision provider:", error);
        const errorMessage =
          error instanceof Error ? error.message : "Unknown error occurred";
        setPopup({
          message: `Failed to update default vision provider: ${errorMessage}`,
          type: "error",
        });
        return false;
      }
    },
    [visionProviders, setPopup, loadVisionProviders]
  );

  // Load providers on mount
  useEffect(() => {
    loadVisionProviders();
  }, [loadVisionProviders]);

  return {
    visionProviders,
    visionLLM,
    isLoading,
    error,
    setVisionLLM,
    updateDefaultVisionProvider,
    refreshVisionProviders: loadVisionProviders,
  };
}
