import { useState, useEffect, useCallback } from "react";
import { ImageGenerationProvider } from "@/app/admin/configuration/llm/interfaces";
import { fetchImageGenerationProviders } from "@/lib/llm/imageGenerationLLM";
import { structureValue } from "@/lib/llm/utils";

// Define a type for the popup setter function
type SetPopup = (popup: {
  message: string;
  type: "success" | "error" | "info";
}) => void;

// Accept the setPopup function as a parameter
export function useImageGenerationProviders(setPopup: SetPopup) {
  const [imageGenerationProviders, setImageGenerationProviders] = useState<
    ImageGenerationProvider[]
  >([]);
  const [imageGenerationLLM, setImageGenerationLLM] = useState<string | null>(
    null
  );
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadImageGenerationProviders = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchImageGenerationProviders();
      setImageGenerationProviders(data);
    } catch (error) {
      console.error("Error fetching image generation providers:", error);
      setError(
        error instanceof Error ? error.message : "Unknown error occurred"
      );
      // Don't show popup for this - it may just mean no providers are configured
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initialize the selected LLM from settings
  const initializeFromSettings = useCallback(
    (providerId: number | null, modelName: string | null) => {
      if (!providerId || !modelName) {
        setImageGenerationLLM(null);
        return;
      }

      const provider = imageGenerationProviders.find(
        (p) => p.id === providerId
      );
      if (provider && provider.image_generation_models.includes(modelName)) {
        setImageGenerationLLM(
          structureValue(provider.name, provider.provider, modelName)
        );
      }
    },
    [imageGenerationProviders]
  );

  // Load providers on mount
  useEffect(() => {
    loadImageGenerationProviders();
  }, [loadImageGenerationProviders]);

  return {
    imageGenerationProviders,
    imageGenerationLLM,
    isLoading,
    error,
    setImageGenerationLLM,
    refreshImageGenerationProviders: loadImageGenerationProviders,
    initializeFromSettings,
  };
}
