import { useState } from "react";
import { LoadingAnimation } from "@/components/Loading";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { Button as OpalButton } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { LLMProviderView } from "@/interfaces/llm";
import { toast } from "@/hooks/useToast";
import { ScopedMutator } from "swr";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { deleteLlmProvider } from "@/lib/llmConfig/svc";
import DeleteProviderModal from "@/sections/modals/llmConfig/components/DeleteProviderModal";

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
  const [showForceDeleteModal, setShowForceDeleteModal] = useState(false);

  const handleDelete = async () => {
    if (!existingLlmProvider) return;

    try {
      await deleteLlmProvider(existingLlmProvider.id);
      await refreshLlmProviderCaches(mutate);
      onClose();
      toast.success("Provider deleted successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      if (message.toLowerCase().includes("default")) {
        setShowForceDeleteModal(true);
      } else {
        toast.error(`Failed to delete provider: ${message}`);
      }
    }
  };

  return (
    <>
      {testError && (
        <Text as="p" className="text-error mt-2">
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

      {showForceDeleteModal && existingLlmProvider && (
        <DeleteProviderModal
          providerId={existingLlmProvider.id}
          providerName={existingLlmProvider.name}
          mutate={mutate}
          onClose={() => setShowForceDeleteModal(false)}
          onDeleted={onClose}
        />
      )}
    </>
  );
}
