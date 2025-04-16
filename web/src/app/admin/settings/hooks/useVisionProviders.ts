import { useState, useEffect, useCallback } from "react";
import { VisionProvider } from "@/app/admin/configuration/llm/interfaces";
import {
  fetchVisionProviders,
  setDefaultVisionProvider,
} from "@/lib/llm/visionLLM";
import { destructureValue, structureValue } from "@/lib/llm/utils";

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
      console.error("Ошибка загрузки поставщиков визуализации:", error);
      setError(
        error instanceof Error ? error.message : "Произошла неизвестная ошибка"
      );
      setPopup({
        message: `Не удалось загрузить поставщиков визуализации: ${
          error instanceof Error ? error.message : "Неизвестная ошибка"
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
          message: "Выберите допустимую модель зрения",
          type: "error",
        });
        return false;
      }

      try {
        const { name, modelName } = destructureValue(llmValue);

        // Find the provider ID
        const providerObj = visionProviders.find((p) => p.name === name);
        if (!providerObj) {
          throw new Error("Провайдер не найден");
        }

        await setDefaultVisionProvider(providerObj.id, modelName);

        setPopup({
          message: "Провайдер по умолчанию успешно обновлен!",
          type: "success",
        });
        setVisionLLM(llmValue);

        // Refresh the list to reflect the change
        await loadVisionProviders();
        return true;
      } catch (error: unknown) {
        console.error("Error setting default vision provider:", error);
        const errorMessage =
          error instanceof Error
            ? error.message
            : "Произошла неизвестная ошибка";
        setPopup({
          message: `Не удалось обновить провайдера визуализации по умолчанию:${errorMessage}`,
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
