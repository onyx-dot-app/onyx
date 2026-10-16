"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Modal, Text } from "@opal/components";
import useOpenApiTools from "@/hooks/useOpenApiTools";
import type { ToolSnapshot } from "@/lib/tools/types";
import OpenApiActionDialogs from "@/sections/actions/OpenApiActionDialogs";

interface OpenApiActionEditorProps {
  toolId: number;
  name: string;
  onClose: () => void;
  onChanged: () => Promise<void>;
}

/** Loads a fresh source action before entering the shared configuration flow. */
export default function OpenApiActionEditor({
  toolId,
  name,
  onClose,
  onChanged,
}: OpenApiActionEditorProps) {
  const t = useTranslations("actions");
  const tApps = useTranslations("admin.externalApps");
  const { openApiTools, error, isLoading, isValidating, mutateOpenApiTools } =
    useOpenApiTools({ revalidateOnMount: true });
  const [initialTool, setInitialTool] = useState<ToolSnapshot>();
  useEffect(() => {
    if (!initialTool && !isLoading && !isValidating && !error) {
      setInitialTool(openApiTools?.find((tool) => tool.id === toolId));
    }
  }, [initialTool, isLoading, isValidating, error, openApiTools, toolId]);

  if (initialTool) {
    return (
      <OpenApiActionDialogs
        initialTool={initialTool}
        onClosed={onClose}
        onChanged={async () => {
          await Promise.all([mutateOpenApiTools(), onChanged()]);
        }}
      />
    );
  }

  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Modal.Content width="sm" height="fit">
        <Modal.Header title={name} onClose={onClose} />
        <Modal.Body>
          <Text font="main-content-body" color="text-03">
            {error || (!isLoading && !isValidating)
              ? t("openApiPage.loadError")
              : tApps("loading.label")}
          </Text>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
