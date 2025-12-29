import { useState } from "react";
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
}

export function FetchModelsButton({
  onFetch,
  isDisabled = false,
  disabledHint,
  onModelsFetched,
  onLoadingChange,
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
        <Text className="text-xs text-status-error-05 mt-1">
          {fetchModelsError}
        </Text>
      )}
    </div>
  );
}
