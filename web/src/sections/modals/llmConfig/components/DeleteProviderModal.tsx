"use client";

import { toast } from "@/hooks/useToast";
import { Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import Text from "@/refresh-components/texts/Text";
import Message from "@/refresh-components/messages/Message";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { Section } from "@/layouts/general-layouts";
import { refreshLlmProviderCaches } from "@/lib/llmConfig/cache";
import { deleteLlmProvider } from "@/lib/llmConfig/svc";
import { ScopedMutator } from "swr";

interface DeleteProviderModalProps {
  providerId: number;
  providerName: string;
  isLastProvider?: boolean;
  mutate: ScopedMutator;
  onClose: () => void;
  onDeleted?: () => void;
}

export default function DeleteProviderModal({
  providerId,
  providerName,
  isLastProvider,
  mutate,
  onClose,
  onDeleted,
}: DeleteProviderModalProps) {
  const handleForceDelete = async () => {
    try {
      await deleteLlmProvider(providerId, true);
      await refreshLlmProviderCaches(mutate);
      onClose();
      onDeleted?.();
      toast.success("Provider deleted successfully!");
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      toast.error(`Failed to delete provider: ${message}`);
    }
  };

  return (
    <ConfirmationModalLayout
      icon={SvgTrash}
      title={`Delete ${providerName}`}
      onClose={onClose}
      submit={
        <Button variant="danger" onClick={handleForceDelete}>
          Delete Anyway
        </Button>
      }
    >
      <Section alignItems="center" gap={0.5}>
        <Message
          warning
          icon
          close={false}
          text="Deleting the Default Provider can cause problems"
          className="w-full"
        />
        <Text text03>
          Are you sure you want to delete {providerName}? They are your default
          provider. Deleting them will result in no default model being set
          which can cause issues. It is recommended to set a new default
          provider/model before deleting.
        </Text>
      </Section>
    </ConfirmationModalLayout>
  );
}
