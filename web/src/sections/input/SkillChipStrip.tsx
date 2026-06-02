"use client";

import { useRef } from "react";
import { cn } from "@opal/utils";
import { Button, Text, Tooltip } from "@opal/components";
import {
  SvgAlertCircle,
  SvgClock,
  SvgFileText,
  SvgImage,
  SvgLoader,
  SvgSparkle,
  SvgX,
} from "@opal/icons";
import { isImageFile } from "@/lib/utils";
import {
  type BuildFile,
  UploadFileStatus,
} from "@/app/craft/contexts/UploadFilesContext";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import type { PickerEntry } from "@/lib/skills/picker";

function BuildFileCard({
  file,
  onRemove,
}: {
  file: BuildFile;
  onRemove: (id: string) => void;
}) {
  const isImage = isImageFile(file.name);
  const isUploading = file.status === UploadFileStatus.UPLOADING;
  const isPending = file.status === UploadFileStatus.PENDING;
  const isFailed = file.status === UploadFileStatus.FAILED;

  const cardContent = (
    <div
      className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-08",
        "bg-background-neutral-01 border",
        "text-sm text-text-04",
        isFailed ? "border-status-error-02" : "border-border-01"
      )}
    >
      {isUploading ? (
        <SvgLoader className="h-4 w-4 animate-spin text-text-03" />
      ) : isPending ? (
        <SvgClock className="h-4 w-4 text-text-03" />
      ) : isFailed ? (
        <SvgAlertCircle className="h-4 w-4 text-status-error-02" />
      ) : isImage ? (
        <SvgImage className="h-4 w-4 text-text-03" />
      ) : (
        <SvgFileText className="h-4 w-4 text-text-03" />
      )}
      <span className="max-w-[120px] truncate">
        <Text font="main-ui-body" color="text-04" nowrap>
          {file.name}
        </Text>
      </span>
      <Button
        variant="default"
        prominence="tertiary"
        size="2xs"
        icon={SvgX}
        onClick={() => onRemove(file.id)}
        aria-label={`Remove ${file.name}`}
      />
    </div>
  );

  if (isFailed && file.error) {
    return (
      <Tooltip tooltip={file.error} side="top">
        {cardContent}
      </Tooltip>
    );
  }
  if (isPending) {
    return (
      <Tooltip tooltip="Waiting for session to be ready..." side="top">
        {cardContent}
      </Tooltip>
    );
  }
  return cardContent;
}

interface SkillChipProps {
  entry: PickerEntry;
  onRemove: () => void;
  onClick?: (chipEl: HTMLElement) => void;
}

function SkillChip({ entry, onRemove, onClick }: SkillChipProps) {
  const chipRef = useRef<HTMLDivElement>(null);
  const Logo = entry.kind === "app" ? getAppTypeLogo(entry.appType) : null;

  return (
    <div
      ref={chipRef}
      className={cn(
        "flex items-center gap-1.5 px-2 py-1 rounded-08",
        "bg-theme-blue-02 border border-theme-blue-04",
        onClick && "cursor-pointer"
      )}
      onClick={() => {
        if (chipRef.current) onClick?.(chipRef.current);
      }}
    >
      {Logo ? (
        <Logo className="h-3.5 w-3.5 text-theme-blue-07" />
      ) : (
        <SvgSparkle className="h-3.5 w-3.5 text-theme-blue-07" />
      )}
      <Text font="main-ui-body" color="text-04" nowrap>
        {entry.name}
      </Text>
      <Button
        variant="default"
        prominence="tertiary"
        size="2xs"
        icon={SvgX}
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        aria-label={`Remove ${entry.name}`}
      />
    </div>
  );
}

export interface SkillChipStripProps {
  files: BuildFile[];
  skills: PickerEntry[];
  onRemoveFile: (id: string) => void;
  onRemoveSkill: (slug: string) => void;
  onClickSkill?: (entry: PickerEntry, chipEl: HTMLElement) => void;
}

export function SkillChipStrip({
  files,
  skills,
  onRemoveFile,
  onRemoveSkill,
  onClickSkill,
}: SkillChipStripProps) {
  if (files.length === 0 && skills.length === 0) return null;

  return (
    <div className="flex flex-wrap gap-1">
      {files.map((file) => (
        <BuildFileCard key={file.id} file={file} onRemove={onRemoveFile} />
      ))}
      {skills.map((entry) => (
        <SkillChip
          key={entry.slug}
          entry={entry}
          onRemove={() => onRemoveSkill(entry.slug)}
          onClick={onClickSkill ? (el) => onClickSkill(entry, el) : undefined}
        />
      ))}
    </div>
  );
}

export default SkillChipStrip;
