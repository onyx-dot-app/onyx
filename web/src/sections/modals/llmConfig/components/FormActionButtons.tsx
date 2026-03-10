import { LoadingAnimation } from "@/components/Loading";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { LLMProviderView } from "@/interfaces/llm";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { deleteLlmProvider } from "@/lib/llmConfig/svc";
import { ScopedMutator } from "swr";

interface FormActionButtonsProps {
  isTesting: boolean;
  testError: string;
  existingLlmProvider?: LLMProviderView;
  mutate: ScopedMutator;
  onClose: () => void;
  isFormValid: boolean;
}

export function FormActionButtons({
  isTesting,
  testError,
  existingLlmProvider,
  mutate,
  onClose,
  isFormValid,
}: FormActionButtonsProps) {
  const handleDelete = async () => {
    if (!existingLlmProvider) return;

    try {
      await deleteLlmProvider(existingLlmProvider.id);
      await refreshLlmProviderCaches(mutate);
      onClose();
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      alert(`Failed to delete provider: ${message}`);
    }
  };

  return (
    <>
      {testError && (
        <Text as="p" className="text-status-text-error-05 mt-2">
          {testError}
        </Text>
      )}

      <div className="flex w-full mt-4 gap-2">
        <Button type="submit" disabled={isTesting || !isFormValid}>
          {isTesting ? (
            <Text as="p" inverted>
              <LoadingAnimation text="Testing" />
            </Text>
          ) : existingLlmProvider ? (
            "Update"
          ) : (
            "Enable"
          )}
        </Button>
        {existingLlmProvider && (
          <OpalButton variant="danger" icon={SvgTrash} onClick={handleDelete}>
            Delete
          </OpalButton>
        )}
      </div>
    </>
  );
}
