"use client";

import { useRef, type ReactNode } from "react";
import { AnimatePresence, motion, useReducedMotion } from "motion/react";
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

interface InputChipProps {
  icon: ReactNode;
  label: string;
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
        "flex items-center gap-1 px-1 py-px rounded-08 border",
        colorClassName,
        onClick && "cursor-pointer"
      )}
      onClick={() => {
        if (chipRef.current) onClick?.(chipRef.current);
      }}
    >
      {icon}
      <span className="max-w-[120px] truncate">
        <Text font="secondary-body" color="inherit" nowrap>
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
    <SvgLoader className="h-3 w-3 shrink-0 animate-spin" />
  ) : isPending ? (
    <SvgClock className="h-3 w-3 shrink-0" />
  ) : isFailed ? (
    <SvgAlertCircle className="h-3 w-3 shrink-0 text-status-error-02" />
  ) : isImage ? (
    <SvgImage className="h-3 w-3 shrink-0" />
  ) : (
    <SvgFileText className="h-3 w-3 shrink-0" />
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

interface EntryChipProps {
  entry: PickerEntry;
  onRemove: () => void;
  onClick?: (chipEl: HTMLElement) => void;
}

function EntryChip({ entry, onRemove, onClick }: EntryChipProps) {
  const Logo = entry.kind === "app" ? getAppTypeLogo(entry.appType) : null;
  const Icon = Logo ?? SvgSparkle;

  return (
    <InputChip
      icon={<Icon className="h-3 w-3 shrink-0" />}
      label={entry.name}
      colorClassName="bg-theme-blue-01 border-theme-blue-03 text-theme-blue-05"
      onRemove={onRemove}
      onClick={onClick}
    />
  );
}

export interface InputChipStripProps {
  files: BuildFile[];
  entries: PickerEntry[];
  onRemoveFile: (id: string) => void;
  onRemoveEntry: (slug: string) => void;
  onClickEntry?: (entry: PickerEntry, chipEl: HTMLElement) => void;
}

const EASE = [0.16, 1, 0.3, 1] as const;

export function InputChipStrip({
  files,
  entries,
  onRemoveFile,
  onRemoveEntry,
  onClickEntry,
}: InputChipStripProps) {
  const reduceMotion = useReducedMotion();
  const hasContent = files.length > 0 || entries.length > 0;

  // Animate height so the bar grows/shrinks smoothly on first/last chip.
  const stripTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.2, ease: EASE };
  const chipTransition = reduceMotion
    ? { duration: 0 }
    : { duration: 0.15, ease: EASE };

  // Entries (skills/apps) lead; files follow.
  return (
    <AnimatePresence initial={false}>
      {hasContent && (
        <motion.div
          key="chip-strip"
          initial={{ height: 0, opacity: 0 }}
          animate={{ height: "auto", opacity: 1 }}
          exit={{ height: 0, opacity: 0 }}
          transition={stripTransition}
          style={{ overflow: "hidden" }}
        >
          <div className="flex flex-wrap gap-1 px-3 pt-2">
            <AnimatePresence initial={false} mode="popLayout">
              {entries.map((entry) => (
                <motion.div
                  key={`entry-${entry.slug}`}
                  layout
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.85 }}
                  transition={chipTransition}
                >
                  <EntryChip
                    entry={entry}
                    onRemove={() => onRemoveEntry(entry.slug)}
                    onClick={
                      onClickEntry ? (el) => onClickEntry(entry, el) : undefined
                    }
                  />
                </motion.div>
              ))}
              {files.map((file) => (
                <motion.div
                  key={`file-${file.id}`}
                  layout
                  initial={{ opacity: 0, scale: 0.85 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.85 }}
                  transition={chipTransition}
                >
                  <BuildFileCard file={file} onRemove={onRemoveFile} />
                </motion.div>
              ))}
            </AnimatePresence>
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

export default InputChipStrip;
