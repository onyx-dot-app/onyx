import { LoadingAnimation } from "@/components/Loading";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { SvgTrash } from "@opal/icons";
import { LLMProviderView } from "@/interfaces/llm";
import { LLM_PROVIDERS_ADMIN_URL } from "@/lib/llmConfig/constants";

interface FormActionButtonsProps {
  isTesting: boolean;
  testError: string;
  existingLlmProvider?: LLMProviderView;
  mutate: (key: string) => void;
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

    const response = await fetch(
      `${LLM_PROVIDERS_ADMIN_URL}/${existingLlmProvider.id}`,
      {
        method: "DELETE",
      }
    );

    if (!response.ok) {
      const errorMsg = (await response.json()).detail;
      alert(`Failed to delete provider: ${errorMsg}`);
      return;
    }

    mutate(LLM_PROVIDERS_ADMIN_URL);
    onClose();
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
          <Button danger leftIcon={SvgTrash} onClick={handleDelete}>
            Delete
          </Button>
        )}
      </div>
    </>
  );
}
