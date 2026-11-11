"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { IconLoader } from "@opal/loaders";
import { toast } from "@opal/layouts";
import { HiddenInput } from "@/layouts/table-layouts";
import { useBuildSessionStore } from "@/app/craft/hooks/useBuildSessionStore";
import { uploadFile } from "@/app/craft/services/apiServices";

interface WorkspaceUploadButtonProps {
  sessionId: string;
  disabled?: boolean;
}

export function WorkspaceUploadButton({
  sessionId,
  disabled = false,
}: WorkspaceUploadButtonProps) {
  const t = useTranslations("craft.filesTab");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [pending, setPending] = useState(false);

  return (
    <>
      <Button
        icon={pending ? IconLoader : SvgUploadCloud}
        prominence="tertiary"
        size="sm"
        disabled={disabled || pending}
        aria-label={t("upload.label")}
        aria-busy={pending}
        onClick={() => fileInputRef.current?.click()}
      >
        {t("upload.label")}
      </Button>
      <HiddenInput
        inputRef={fileInputRef}
        type="file"
        hidden
        disabled={disabled || pending}
        aria-label={t("upload.label")}
        multiple
        onChange={async (event) => {
          const files = Array.from(event.currentTarget.files ?? []);
          event.currentTarget.value = "";
          if (!files.length || disabled || pending) return;
          setPending(true);
          let uploaded = false;
          try {
            for (const file of files) {
              await uploadFile(sessionId, file);
              uploaded = true;
            }
          } catch {
            toast.error(t("upload.error"));
          } finally {
            if (uploaded)
              useBuildSessionStore.getState().triggerFilesRefresh(sessionId);
            setPending(false);
          }
        }}
      />
    </>
  );
}
