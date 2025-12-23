import { useState } from "react";
import Button from "@/refresh-components/buttons/Button";
import { LoadingAnimation } from "@/components/Loading";
import Text from "@/refresh-components/texts/Text";
import { fetchModels } from "../../utils";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import {
  LLMProviderView,
  ModelConfiguration,
  WellKnownLLMProviderDescriptor,
} from "../../interfaces";

interface FetchModelsButtonProps {
  descriptor: WellKnownLLMProviderDescriptor;
  existingLlmProvider?: LLMProviderView;
  values: any;
  setFieldValue: (field: string, value: any) => void;
  setPopup: (popup: PopupSpec) => void;
  isDisabled?: boolean;
  disabledHint?: string;
}

export function FetchModelsButton({
  descriptor,
  existingLlmProvider,
  values,
  setFieldValue,
  setPopup,
  isDisabled = false,
  disabledHint,
}: FetchModelsButtonProps) {
  const [isFetchingModels, setIsFetchingModels] = useState(false);
  const [fetchModelsError, setFetchModelsError] = useState("");

  const handleFetchModels = async () => {
    await fetchModels(
      descriptor,
      existingLlmProvider,
      values,
      setFieldValue,
      setIsFetchingModels,
      setFetchModelsError,
      setPopup
    );
  };

  return (
    <div className="flex flex-col gap-y-2">
      <div className="flex items-center gap-x-4">
        <Button
          type="button"
          onClick={handleFetchModels}
          disabled={isFetchingModels || isDisabled}
        >
          {isFetchingModels ? <LoadingAnimation /> : "Fetch Available Models"}
        </Button>
        {fetchModelsError && (
          <Text className="text-sm text-error">{fetchModelsError}</Text>
        )}
      </div>
      {isDisabled && disabledHint && (
        <Text mainUiMuted className="text-sm">
          {disabledHint}
        </Text>
      )}
    </div>
  );
}
