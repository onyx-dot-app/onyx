"use client";

import { useState } from "react";
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
}

function CraftMessageImage({ sessionId, attachment }: CraftMessageImageProps) {
  const [failed, setFailed] = useState(false);
  const download = () => downloadArtifactFile(sessionId, attachment.path);

  if (failed) {
    return <Attachment fileName={attachment.name} open={download} />;
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
          className="max-h-72 max-w-112 object-contain object-right"
          onError={() => setFailed(true)}
        />
        <div className="absolute bottom-2 right-2">
          <Hoverable.Item group="craftMessageImage" variant="appear-on-hover">
            <Button
              icon={SvgDownload}
              prominence="secondary"
              size="sm"
              tooltip={`Download ${attachment.name}`}
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
}

export default function CraftMessageAttachments({
  sessionId,
  attachments,
  refreshKey = 0,
}: CraftMessageAttachmentsProps) {
  if (attachments.length === 0) return null;

  return (
    <div className="flex w-full flex-wrap justify-end gap-2 pb-2">
      {attachments.map((attachment) =>
        attachment.mimeType.startsWith("image/") ? (
          <CraftMessageImage
            key={`${attachment.path}-${refreshKey}`}
            sessionId={sessionId}
            attachment={attachment}
          />
        ) : (
          <Attachment
            key={attachment.path}
            fileName={attachment.name}
            open={() => downloadArtifactFile(sessionId, attachment.path)}
          />
        )
      )}
    </div>
  );
}
