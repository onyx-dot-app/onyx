"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Section } from "@opal/layouts";
import { Button } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgDownload } from "@opal/icons";
import Attachment from "@/refresh-components/Attachment";
import {
  buildArtifactUrl,
  downloadArtifactFile,
} from "@/app/craft/services/apiServices";
import type { BuildMessageAttachment } from "@/app/craft/types/streamingTypes";

interface CraftMessageImageProps {
  sessionId: string;
  attachment: BuildMessageAttachment;
  onFileOpen?: (path: string, fileName: string) => void;
}

function CraftMessageImage({
  sessionId,
  attachment,
  onFileOpen,
}: CraftMessageImageProps) {
  const t = useTranslations("craft.filePreview");
  const [failed, setFailed] = useState(false);
  const download = () => downloadArtifactFile(sessionId, attachment.path);

  if (failed) {
    return (
      <Attachment
        fileName={attachment.name}
        open={
          onFileOpen
            ? () => onFileOpen(attachment.path, attachment.name)
            : undefined
        }
      />
    );
  }

  return (
    <Hoverable.Root group="craftMessageImage" width="fit">
      <div className="relative overflow-hidden rounded-12 bg-background-tint-01">
        <img
          src={buildArtifactUrl(sessionId, attachment.path)}
          alt={attachment.name}
          width={448}
          height={288}
          loading="lazy"
          className="max-h-72 max-w-112 object-contain object-right rtl:object-left"
          onError={() => setFailed(true)}
        />
        <div className="absolute bottom-2 end-2">
          <Hoverable.Item group="craftMessageImage" variant="appear-on-hover">
            <Button
              icon={SvgDownload}
              prominence="secondary"
              size="sm"
              tooltip={t("download.label")}
              onClick={download}
            />
          </Hoverable.Item>
        </div>
      </div>
    </Hoverable.Root>
  );
}

interface CraftMessageAttachmentsProps {
  sessionId: string;
  attachments: BuildMessageAttachment[];
  refreshKey?: number;
  onFileOpen?: (path: string, fileName: string) => void;
}

export default function CraftMessageAttachments({
  sessionId,
  attachments,
  refreshKey = 0,
  onFileOpen,
}: CraftMessageAttachmentsProps) {
  if (attachments.length === 0) return null;

  return (
    <Section
      height="auto"
      flexDirection="row"
      wrap
      justifyContent="end"
      gap={2}
      className="mb-2"
    >
      {attachments.map((attachment) =>
        attachment.mimeType.startsWith("image/") ? (
          <CraftMessageImage
            key={`${attachment.path}-${refreshKey}`}
            sessionId={sessionId}
            attachment={attachment}
            onFileOpen={onFileOpen}
          />
        ) : (
          <Attachment
            key={attachment.path}
            fileName={attachment.name}
            open={
              onFileOpen
                ? () => onFileOpen(attachment.path, attachment.name)
                : undefined
            }
          />
        )
      )}
    </Section>
  );
}
