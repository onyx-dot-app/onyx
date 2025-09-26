import { Button } from "@/components/ui/button";
import { FiRefreshCw } from "react-icons/fi";
import { useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { LoadingAnimation } from "@/components/Loading";

interface FetchOllamaModelsButtonProps {
  apiBase: string;
  setModels: (models: string[]) => void;
  setPopup: (popup: PopupSpec) => void;
  disabled?: boolean;
}

export function FetchOllamaModelsButton({
  apiBase,
  setModels,
  setPopup,
  disabled = false,
}: FetchOllamaModelsButtonProps) {
  const [isFetching, setIsFetching] = useState(false);

  const fetchModels = async () => {
    // Normalize API base: trim and ensure scheme
    let base = (apiBase || "").trim();
    if (base && !/^https?:\/\//i.test(base)) {
      base = `http://${base}`;
    }

    if (!base) {
      setPopup({
        message: "Please enter an Ollama server URL first",
        type: "error",
      });
      return;
    }

    setIsFetching(true);
    try {
      const response = await fetch(`/api/admin/llm/ollama/models?api_base=${encodeURIComponent(base)}`);
      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to fetch models");
      }
      const models = await response.json();
      setModels(models);
      setPopup({
        message: `Found ${models.length} model(s)`,
        type: "success",
      });
    } catch (error) {
      console.error("Error fetching Ollama models:", error);
      setPopup({
        message: `Error fetching models: ${error instanceof Error ? error.message : String(error)}`,
        type: "error",
      });
    } finally {
      setIsFetching(false);
    }
  };

  return (
    <Button
      onClick={fetchModels}
      disabled={disabled || isFetching}
      className="flex items-center gap-2"
      type="button"
      variant="outline"
    >
      {isFetching ? (
        <LoadingAnimation text="" />
      ) : (
        <>
          <FiRefreshCw className="h-4 w-4" />
          Fetch Available Models
        </>
      )}
    </Button>
  );
}
