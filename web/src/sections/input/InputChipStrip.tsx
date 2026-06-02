"use client";

import { useRef, type ReactNode } from "react";
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

// ── Shared chip primitive ─────────────────────────────────────────────────────

interface InputChipProps {
  icon: ReactNode;
  label: string;
  /** Tailwind classes for bg, border, and text color. */
  colorClassName: string;
  onRemove: () => void;
  onClick?: (chipEl: HTMLElement) => void;
}

function InputChip({
  icon,
  label,
  colorClassName,
  onRemove,
  onClick,
}: InputChipProps) {
  const chipRef = useRef<HTMLDivElement>(null);

  return (
    <div
      ref={chipRef}
      className={cn(
        "flex items-center gap-1 px-1.5 py-0.5 rounded-08 border",
        colorClassName,
        onClick && "cursor-pointer"
      )}
      onClick={() => {
        if (chipRef.current) onClick?.(chipRef.current);
      }}
    >
      {icon}
      <span className="max-w-[120px] truncate">
        <Text font="main-ui-body" color="inherit" nowrap>
          {label}
        </Text>
      </span>
      <Button
        variant="default"
        prominence="tertiary"
        size="2xs"
        icon={SvgX}
        onClick={(e) => {
          e.stopPropagation();
          onRemove();
        }}
        aria-label={`Remove ${label}`}
      />
    </div>
  );
}

// ── File chip ─────────────────────────────────────────────────────────────────

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

  const icon = isUploading ? (
    <SvgLoader className="h-3.5 w-3.5 shrink-0 animate-spin" />
  ) : isPending ? (
    <SvgClock className="h-3.5 w-3.5 shrink-0" />
  ) : isFailed ? (
    <SvgAlertCircle className="h-3.5 w-3.5 shrink-0 text-status-error-02" />
  ) : isImage ? (
    <SvgImage className="h-3.5 w-3.5 shrink-0" />
  ) : (
    <SvgFileText className="h-3.5 w-3.5 shrink-0" />
  );

  const chip = (
    <InputChip
      icon={icon}
      label={file.name}
      colorClassName={cn(
        "bg-background-neutral-01 text-text-04",
        isFailed ? "border-status-error-02" : "border-border-01"
      )}
      onRemove={() => onRemove(file.id)}
    />
  );

  if (isFailed && file.error) {
    return (
      <Tooltip tooltip={file.error} side="top">
        {chip}
      </Tooltip>
    );
  }
  if (isPending) {
    return (
      <Tooltip tooltip="Waiting for session to be ready..." side="top">
        {chip}
      </Tooltip>
    );
  }
  return chip;
}

// ── Skill / app chip ──────────────────────────────────────────────────────────

interface SkillChipProps {
  entry: PickerEntry;
  onRemove: () => void;
  onClick?: (chipEl: HTMLElement) => void;
}

function SkillChip({ entry, onRemove, onClick }: SkillChipProps) {
  const Logo = entry.kind === "app" ? getAppTypeLogo(entry.appType) : null;
  const Icon = Logo ?? SvgSparkle;

  return (
    <InputChip
      icon={<Icon className="h-3.5 w-3.5 shrink-0" />}
      label={entry.name}
      colorClassName="bg-theme-blue-01 border-theme-blue-03 text-theme-blue-05"
      onRemove={onRemove}
      onClick={onClick}
    />
  );
}

// ── Strip ─────────────────────────────────────────────────────────────────────

export interface InputChipStripProps {
  files: BuildFile[];
  skills: PickerEntry[];
  onRemoveFile: (id: string) => void;
  onRemoveSkill: (slug: string) => void;
  onClickSkill?: (entry: PickerEntry, chipEl: HTMLElement) => void;
}

export function InputChipStrip({
  files,
  skills,
  onRemoveFile,
  onRemoveSkill,
  onClickSkill,
}: InputChipStripProps) {
  if (files.length === 0 && skills.length === 0) return null;

  // Single wrapping row. Skills/apps lead (flush left), files follow.
  return (
    <div className="flex flex-wrap gap-1">
      {skills.map((entry) => (
        <SkillChip
          key={entry.slug}
          entry={entry}
          onRemove={() => onRemoveSkill(entry.slug)}
          onClick={onClickSkill ? (el) => onClickSkill(entry, el) : undefined}
        />
      ))}
      {files.map((file) => (
        <BuildFileCard key={file.id} file={file} onRemove={onRemoveFile} />
      ))}
    </div>
  );
}

export default InputChipStrip;
