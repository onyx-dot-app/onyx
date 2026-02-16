import { useState, useEffect, useCallback } from "react";
import { VisionProvider } from "@/app/admin/configuration/llm/interfaces";
import {
  fetchVisionProviders,
  setDefaultVisionProvider,
} from "@/lib/llm/visionLLM";
import { parseLlmDescriptor, structureValue } from "@/lib/llm/utils";
import { toast } from "@/hooks/useToast";

export function useVisionProviders() {
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
      toast.error(
        `Failed to load vision providers: ${
          error instanceof Error ? error.message : "Unknown error"
        }`
      );
    } finally {
      setIsLoading(false);
    }
  }, []);

  const updateDefaultVisionProvider = useCallback(
    async (llmValue: string | null) => {
      if (!llmValue) {
        toast.error("Please select a valid vision model");
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

        toast.success("Default vision provider updated successfully!");
        setVisionLLM(llmValue);

        // Refresh the list to reflect the change
        await loadVisionProviders();
        return true;
      } catch (error: unknown) {
        console.error("Error setting default vision provider:", error);
        const errorMessage =
          error instanceof Error ? error.message : "Unknown error occurred";
        toast.error(
          `Failed to update default vision provider: ${errorMessage}`
        );
        return false;
      }
    },
    [visionProviders, loadVisionProviders]
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
