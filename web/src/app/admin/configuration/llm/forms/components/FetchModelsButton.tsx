import { useState, useEffect } from "react";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import { ModelConfiguration } from "../../interfaces";

interface FetchModelsButtonProps {
  onFetch: () => Promise<{ models: ModelConfiguration[]; error?: string }>;
  isDisabled?: boolean;
  disabledHint?: string;
  onModelsFetched: (models: ModelConfiguration[]) => void;
  onLoadingChange?: (isLoading: boolean) => void;
  autoFetchOnInitialLoad?: boolean;
}

export function FetchModelsButton({
  onFetch,
  isDisabled = false,
  disabledHint,
  onModelsFetched,
  onLoadingChange,
  autoFetchOnInitialLoad = false,
}: FetchModelsButtonProps) {
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState("");

  const handleFetchModels = async () => {
    setIsFetchingModels(true);
    onLoadingChange?.(true);
    setFetchModelsError("");

    try {
      const { models, error } = await onFetch();

      if (error) {
        setFetchModelsError(error);
      } else {
        onModelsFetched(models);
      }
    } catch (err) {
      const errorMessage =
        err instanceof Error ? err.message : "Unknown error occurred";
      setFetchModelsError(errorMessage);
    } finally {
      setIsFetchingModels(false);
      onLoadingChange?.(false);
    }
  };

  // Auto-fetch models on initial load if enabled and not disabled
  useEffect(() => {
    if (autoFetchOnInitialLoad && !isDisabled) {
      handleFetchModels();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-y-1">
      <SimpleTooltip tooltip={isDisabled ? disabledHint : undefined} side="top">
        <div className="w-fit">
          <Button
            type="button"
            onClick={handleFetchModels}
            disabled={isFetchingModels || isDisabled}
          >
            Fetch Available Models
          </Button>
        </div>
      </SimpleTooltip>
      {fetchModelsError && (
        <Text as="p" className="text-xs text-status-error-05 mt-1">
          {fetchModelsError}
        </Text>
      )}
    </div>
  );
}
