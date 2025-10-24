"use client";

import React, { useMemo, useRef, useState, useEffect } from "react";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import { noProp } from "@/lib/utils";
import { ProjectFile } from "@/app/chat/projects/ProjectsContext";
import { formatRelativeTime } from "@/app/chat/components/projects/project_utils";
import Text from "@/refresh-components/texts/Text";
import SvgX from "@/icons/x";
import { SvgProps } from "@/icons";
import SvgExternalLink from "@/icons/external-link";
import SvgFileText from "@/icons/file-text";
import SvgImage from "@/icons/image";
import SvgTrash from "@/icons/trash";
import SvgCheck from "@/icons/check";
import { isImageExtension } from "@/app/chat/components/files/files_utils";
import { UserFileStatus } from "@/app/chat/projects/projectsService";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import VerticalShadowScroller from "@/refresh-components/VerticalShadowScroller";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import LineItem from "@/refresh-components/buttons/LineItem";

const getFileExtension = (fileName: string): string => {
  const idx = fileName.lastIndexOf(".");
  if (idx === -1) return "";
  const ext = fileName.slice(idx + 1).toLowerCase();
  if (ext === "txt") return "PLAINTEXT";
  return ext.toUpperCase();
};

export interface UserFilesModalProps {
  title: string;
  description: string;
  icon: React.FunctionComponent<SvgProps>;
  recentFiles: ProjectFile[];
  onPickRecent?: (file: ProjectFile) => void;
  onUnpickRecent?: (file: ProjectFile) => void;
  handleUploadChange?: (e: React.ChangeEvent<HTMLInputElement>) => void;
  showRemove?: boolean;
  onRemove?: (file: ProjectFile) => void;
  onFileClick?: (file: ProjectFile) => void;
  onClose?: () => void;
  selectedFileIds?: string[];
}

export default function UserFilesModalContent({
  title,
  description,
  icon: Icon,
  recentFiles,
  onPickRecent,
  onUnpickRecent,
  handleUploadChange,
  showRemove,
  onRemove,
  onFileClick,
  onClose,
  selectedFileIds,
}: UserFilesModalProps) {
  const [search, setSearch] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(
    () => new Set(selectedFileIds || [])
  );
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const triggerUploadPicker = () => fileInputRef.current?.click();

  useEffect(() => {
    if (selectedFileIds) {
      setSelectedIds(new Set(selectedFileIds));
    } else {
      setSelectedIds(new Set());
    }
  }, [selectedFileIds]);

  const filtered = useMemo(() => {
    const s = search.trim().toLowerCase();
    if (!s) return recentFiles;
    return recentFiles.filter((f) => f.name.toLowerCase().includes(s));
  }, [recentFiles, search]);

  return (
    <>
      {/* Hidden file input */}
      {handleUploadChange && (
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleUploadChange}
        />
      )}

      {/* Title section */}
      <div className="flex flex-col gap-spacing-inline px-spacing-paragraph pt-spacing-paragraph">
        <div className="h-[1.5rem] flex flex-row justify-between items-center w-full">
          <Icon className="w-[1.5rem] h-[1.5rem] stroke-text-04" />
          {onClose && <IconButton icon={SvgX} internal onClick={onClose} />}
        </div>
        <Text headingH3 text04 className="w-full text-left">
          {title}
        </Text>
        <Text text03>{description}</Text>
      </div>

      {/* Search bar section */}
      <div
        tabIndex={-1}
        onMouseDown={(e) => {
          e.stopPropagation();
        }}
      >
        <div className="flex items-center gap-spacing-interline p-padding-button">
          <InputTypeIn
            placeholder="Search files..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            leftSearchIcon
            autoComplete="off"
            tabIndex={0}
            onFocus={(e) => {
              e.target.select();
            }}
          />
          {handleUploadChange && (
            <CreateButton
              onClick={triggerUploadPicker}
              secondary={false}
              internal
            >
              Add Files
            </CreateButton>
          )}
        </div>
      </div>

      {/* File display section */}
      <div className="bg-background-tint-01 overflow-hidden">
        {filtered.length === 0 ? (
          <div className="p-spacing-paragraph flex w-full h-full items-center justify-center">
            <Text text03>No files found</Text>
          </div>
        ) : (
          <VerticalShadowScroller className="px-spacing-aragraph max-h-[30rem]">
            {filtered.map((f) => (
              <LineItem
                key={f.id}
                onClick={() => {
                  if (!onPickRecent) return;
                  const isSelected = selectedIds.has(f.id);
                  if (isSelected) {
                    onUnpickRecent?.(f);
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      next.delete(f.id);
                      return next;
                    });
                  } else {
                    onPickRecent(f);
                    setSelectedIds((prev) => {
                      const next = new Set(prev);
                      next.add(f.id);
                      return next;
                    });
                  }
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    e.currentTarget.click();
                  }
                }}
                icon={({ className }) =>
                  String((f as ProjectFile).status) ===
                    UserFileStatus.PROCESSING ||
                  String((f as ProjectFile).status) ===
                    UserFileStatus.UPLOADING ||
                  String((f as ProjectFile).status) ===
                    UserFileStatus.DELETING ? (
                    <SimpleLoader className={className} />
                  ) : (
                    <>
                      {onPickRecent && selectedIds.has(f.id) ? (
                        <SvgCheck className={className} />
                      ) : (
                        (() => {
                          const ext = getFileExtension(f.name).toLowerCase();
                          const isImage = isImageExtension(ext);
                          return isImage ? (
                            <SvgImage className={className} />
                          ) : (
                            <SvgFileText className={className} />
                          );
                        })()
                      )}
                    </>
                  )
                }
                description={(() => {
                  const s = String(f.status || "");
                  const typeLabel = getFileExtension(f.name);
                  if (s === UserFileStatus.PROCESSING) return "Processing...";
                  if (s === UserFileStatus.UPLOADING) return "Uploading...";
                  if (s === UserFileStatus.DELETING) return "Deleting...";
                  if (s === UserFileStatus.COMPLETED) return typeLabel;
                  return f.status ? f.status : typeLabel;
                })()}
                rightChildren={
                  <div className="flex flex-col justify-center">
                    <div className="group-hover/LineItem:hidden">
                      {f.last_accessed_at && (
                        <Text text03 secondaryBody nowrap>
                          {formatRelativeTime(f.last_accessed_at)}
                        </Text>
                      )}
                    </div>
                    <div className="hidden group-hover/LineItem:flex flex-row">
                      {onFileClick &&
                        String(f.status) !== UserFileStatus.PROCESSING &&
                        String(f.status) !== UserFileStatus.UPLOADING &&
                        String(f.status) !== UserFileStatus.DELETING && (
                          <IconButton
                            internal
                            icon={SvgExternalLink}
                            tooltip="View file"
                            onClick={noProp((event) => {
                              event.preventDefault();
                              onFileClick(f);
                            })}
                          />
                        )}
                      {showRemove &&
                        String(f.status) !== UserFileStatus.UPLOADING &&
                        String(f.status) !== UserFileStatus.DELETING && (
                          <IconButton
                            internal
                            icon={SvgTrash}
                            tooltip="Remove from project"
                            onClick={noProp(() => onRemove?.(f))}
                          />
                        )}
                    </div>
                  </div>
                }
              >
                {f.name}
              </LineItem>
            ))}
          </VerticalShadowScroller>
        )}
      </div>
    </>
  );
}
