"use client";

import { useTranslations } from "next-intl";
import { MessageCard } from "@opal/components";
import { cn } from "@opal/utils";
import type { FileIndexingReason } from "@/lib/projects/utils";

interface FileIndexingBannerProps {
  reason: FileIndexingReason | null;
  onClose: () => void;
}

/** Explains above the input bar why send waits for attached files to index. */
function FileIndexingBanner({ reason, onClose }: FileIndexingBannerProps) {
  const t = useTranslations("chat.input.fileIndexingBanner");

  return (
    <div
      className={cn(
        "transition-all duration-150",
        reason ? "opacity-100 pb-1.5" : "opacity-0 h-0 overflow-hidden"
      )}
    >
      {reason && (
        <MessageCard
          variant="pending"
          title={t(`${reason}.title`)}
          description={t(`${reason}.description`)}
          outerPadding={1}
          innerPadding={1}
          onClose={onClose}
        />
      )}
    </div>
  );
}

export default FileIndexingBanner;
