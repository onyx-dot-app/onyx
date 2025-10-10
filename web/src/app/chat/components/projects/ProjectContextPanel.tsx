"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import { Loader2, X } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { useProjectsContext } from "../../projects/ProjectsContext";
import FilePicker from "../files/FilePicker";
import type {
  ProjectFile,
  CategorizedFiles,
} from "../../projects/projectsService";
import { UserFileStatus } from "../../projects/projectsService";
import { ChatFileType } from "@/app/chat/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import Button from "@/refresh-components/buttons/Button";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgPlusCircle from "@/icons/plus-circle";
import LineItem from "@/refresh-components/buttons/LineItem";
import {
  useChatModal,
  ModalIds,
} from "@/refresh-components/contexts/ChatModalContext";
import AddInstructionModal from "@/components/modals/AddInstructionModal";
import UserFilesModalContent from "@/components/modals/UserFilesModalContent";
import { useEscape } from "@/hooks/useKeyPress";
import CoreModal from "@/refresh-components/modals/CoreModal";
import Text from "@/refresh-components/Text";
import SvgFileText from "@/icons/file-text";
import SvgFolderOpen from "@/icons/folder-open";
import SvgEditBig from "@/icons/edit-big";
import SvgAddLines from "@/icons/add-lines";
import SvgFiles from "@/icons/files";
import Truncated from "@/refresh-components/Truncated";

export function FileCard({
  file,
  removeFile,
  hideProcessingState = false,
  onFileClick,
  isAttaching,
}: {
  file: ProjectFile;
  removeFile: (fileId: string) => void;
  hideProcessingState?: boolean;
  onFileClick?: (file: ProjectFile) => void;
  isAttaching?: boolean;
}) {
  const typeLabel = useMemo(() => {
    const name = String(file.name || "");
    const lastDotIndex = name.lastIndexOf(".");
    if (lastDotIndex <= 0 || lastDotIndex === name.length - 1) {
      return "";
    }
    return name.slice(lastDotIndex + 1).toUpperCase();
  }, [file.name]);

  const isActuallyProcessing =
    String(file.status) === UserFileStatus.UPLOADING ||
    String(file.status) === UserFileStatus.PROCESSING;

  // When hideProcessingState is true, we treat processing files as completed for display purposes
  const isProcessing = hideProcessingState ? false : isActuallyProcessing;

  const handleRemoveFile = async (e: React.MouseEvent) => {
    e.stopPropagation();
    removeFile(file.id);
  };

  return (
    <div
      className={`relative group flex items-center gap-3 border border-border-01 rounded-12 ${
        isProcessing ? "bg-background-neutral-02" : "bg-background-tint-00"
      } p-spacing-inline h-14 w-40 ${
        onFileClick && !isProcessing
          ? "cursor-pointer hover:bg-accent-background"
          : ""
      }`}
      onClick={() => {
        if (onFileClick && !isProcessing) {
          onFileClick(file);
        }
      }}
    >
      {String(file.status) !== UserFileStatus.UPLOADING && (
        <button
          onClick={handleRemoveFile}
          title="Delete file"
          aria-label="Delete file"
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-[#1f1f1f] text-white dark:bg-[#fefcfa] dark:text-black shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
        >
          <X className="h-4 w-4 dark:text-dark-tremor-background-muted" />
        </button>
      )}
      <div
        className={`flex h-9 w-9 items-center justify-center rounded-08 p-spacing-interline
      ${isProcessing ? "bg-background-neutral-03" : "bg-background-tint-01"}`}
      >
        {isProcessing ? (
          <Loader2 className="h-5 w-5 text-text-01 animate-spin" />
        ) : (
          <SvgFileText className="h-5 w-5 stroke-text-02" />
        )}
      </div>
      <div className="flex flex-col overflow-hidden relative">
        <Truncated
          className={`font-secondary-action truncate
          ${isProcessing ? "text-text-03" : "text-text-04"}`}
          title={file.name}
        >
          {file.name}
        </Truncated>
        {isProcessing && (
          <Text text03 secondaryBody nowrap className="truncate">
            {isAttaching
              ? "Attaching..."
              : file.status === UserFileStatus.UPLOADING
                ? "Uploading..."
                : "Processing..."}
          </Text>
        )}
        <div
          className={`absolute right-0 top-0 bottom-0 w-8 pointer-events-none ${
            isProcessing
              ? "bg-gradient-to-l from-background-neutral-02 to-transparent"
              : "bg-gradient-to-l from-background-tint-00 to-transparent"
          }`}
        />
      </div>
    </div>
  );
}

export default function ProjectContextPanel({
  projectTokenCount = 0,
  availableContextTokens = 128_000,
  setPresentingDocument,
}: {
  projectTokenCount?: number;
  availableContextTokens?: number;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
}) {
  const { popup, setPopup } = usePopup();
  const [tempProjectFiles, setTempProjectFiles] = useState<ProjectFile[]>([]);
  const [pendingLinkedFiles, setPendingLinkedFiles] = useState<ProjectFile[]>(
    []
  );
  const [renamingTitle, setRenamingTitle] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const titleInputRef = React.useRef<HTMLInputElement>(null);
  const [showEditIcon, setShowEditIcon] = useState(false);
  const editIconHideRef = React.useRef<number | null>(null);
  // Track recently added files to pin them on the left
  const [recentlyAddedIds, setRecentlyAddedIds] = useState<string[]>([]);
  // Optimistic removal buffer for files removed from the project
  const [optimisticallyRemovedIds, setOptimisticallyRemovedIds] = useState<
    Set<string>
  >(new Set());
  const { isOpen, toggleModal } = useChatModal();
  const open = isOpen(ModalIds.ProjectFilesModal);

  const onClose = () => toggleModal(ModalIds.ProjectFilesModal, false);
  useEscape(onClose, open);

  // Convert ProjectFile to MinimalOnyxDocument format for viewing
  const handleFileClick = useCallback(
    (file: ProjectFile) => {
      if (!setPresentingDocument) return;

      const documentForViewer: MinimalOnyxDocument = {
        document_id: `project_file__${file.file_id}`,
        semantic_identifier: file.name,
      };

      setPresentingDocument(documentForViewer);
    },
    [setPresentingDocument]
  );
  const {
    currentProjectDetails,
    currentProjectId,
    projects,
    uploadFiles,
    recentFiles,
    unlinkFileFromProject,
    linkFileToProject,
    renameProject,
  } = useProjectsContext();
  const [isUploading, setIsUploading] = useState(false);

  const visibleFiles = useMemo(() => {
    const byId = new Map<string, ProjectFile>();
    // Insert temp files first so new uploads appear at the front immediately
    tempProjectFiles.forEach((f) => byId.set(f.id, f));
    // Then insert pending linked files (show as processing)
    pendingLinkedFiles.forEach((f) => byId.set(f.id, f));
    // Then insert backend files to overwrite temp entries while keeping order
    (currentProjectDetails?.files || []).forEach((f) => {
      byId.set(f.id, f);
    });
    const base = Array.from(byId.values()).filter(
      (f) => !optimisticallyRemovedIds.has(f.id)
    );
    if (recentlyAddedIds.length === 0) return base;
    const map = new Map(base.map((f) => [f.id, f] as const));
    const ordered: ProjectFile[] = [];
    for (const id of recentlyAddedIds) {
      const item = map.get(id);
      if (item) {
        ordered.push(item);
        map.delete(id);
      }
    }
    for (const f of base) {
      if (map.has(f.id)) ordered.push(f);
    }
    return ordered;
  }, [
    tempProjectFiles,
    pendingLinkedFiles,
    currentProjectDetails?.files,
    optimisticallyRemovedIds,
    recentlyAddedIds,
  ]);

  const pendingIds = useMemo(
    () => new Set(pendingLinkedFiles.map((f) => f.id)),
    [pendingLinkedFiles]
  );

  const markRecentlyAdded = useCallback((ids: string[]) => {
    if (!ids || ids.length === 0) return;
    setRecentlyAddedIds((prev) => {
      const newSet = new Set(ids);
      const rest = prev.filter((id) => !newSet.has(id));
      return [...ids, ...rest];
    });
  }, []);

  const unmarkRecentlyAdded = useCallback((id: string) => {
    setRecentlyAddedIds((prev) => prev.filter((x) => x !== id));
  }, []);

  const removeFileOptimistic = useCallback(
    async (fileId: string) => {
      if (!currentProjectId) return;
      setOptimisticallyRemovedIds((prev) => new Set(prev).add(fileId));
      unmarkRecentlyAdded(fileId);
      try {
        await unlinkFileFromProject(currentProjectId, fileId);
      } catch (e) {
        // Revert on failure and notify user
        setOptimisticallyRemovedIds((prev) => {
          const next = new Set(prev);
          next.delete(fileId);
          return next;
        });
        setPopup({
          type: "error",
          message: "Failed to remove file from project. Please try again.",
        });
      }
    },
    [currentProjectId, unlinkFileFromProject, setPopup, unmarkRecentlyAdded]
  );

  // Reconcile pending linked files once backend reflects them
  React.useEffect(() => {
    const presentIds = new Set(
      (currentProjectDetails?.files || []).map((f) => f.id)
    );
    if (presentIds.size === 0) return;
    setPendingLinkedFiles((prev) => prev.filter((f) => !presentIds.has(f.id)));
  }, [currentProjectDetails?.files]);

  const handleUploadFiles = useCallback(
    async (files: File[]) => {
      if (!files || files.length === 0) return;
      setIsUploading(true);
      try {
        // Show temporary uploading files immediately
        const tempFiles: ProjectFile[] = Array.from(files).map((file) => ({
          id: file.name,
          file_id: file.name,
          name: file.name,
          project_id: currentProjectId,
          user_id: null,
          created_at: new Date().toISOString(),
          status: UserFileStatus.UPLOADING,
          file_type: file.type,
          last_accessed_at: new Date().toISOString(),
          chat_file_type: ChatFileType.DOCUMENT,
          token_count: 0,
          chunk_count: 0,
        }));
        setTempProjectFiles((prev) => [...tempFiles, ...prev]);

        const result: CategorizedFiles = await uploadFiles(
          Array.from(files),
          currentProjectId
        );
        // Replace the first N temp entries with backend entries so they stay at the front
        setTempProjectFiles((prev) => [
          ...result.user_files,
          ...prev.slice(tempFiles.length),
        ]);
        // Pin the uploaded files to the left in preview/order
        markRecentlyAdded(result.user_files.map((f) => f.id));
        const unsupported = result?.unsupported_files || [];
        const nonAccepted = result?.non_accepted_files || [];
        if (unsupported.length > 0 || nonAccepted.length > 0) {
          const parts: string[] = [];
          if (unsupported.length > 0) {
            parts.push(`File type not supported: ${unsupported.join(", ")}`);
          }
          if (nonAccepted.length > 0) {
            parts.push(
              `Content exceeds allowed token limit: ${nonAccepted.join(", ")}`
            );
          }
          setPopup({
            type: "warning",
            message: `Some files were not uploaded. ${parts.join(" | ")}`,
          });
        }
      } finally {
        setIsUploading(false);
        setTempProjectFiles([]);
      }
    },
    [currentProjectId, uploadFiles, setPopup, markRecentlyAdded]
  );

  // Start renaming -> seed draft and focus
  const startRenamingTitle = useCallback(() => {
    setTitleDraft(currentProjectDetails?.project?.name || "");
    setRenamingTitle(true);
    setTimeout(() => titleInputRef.current?.focus(), 0);
  }, [currentProjectDetails?.project?.name]);

  const commitRenameTitle = useCallback(async () => {
    if (!renamingTitle) return;
    const newName = titleDraft.trim();
    setRenamingTitle(false);
    if (!currentProjectId) return;
    const oldName = currentProjectDetails?.project?.name || "";
    if (!newName || newName === oldName) return;
    // Optimistic rename handled in context; fire-and-forget with error popup
    renameProject(currentProjectId, newName).catch(() => {
      setPopup({ type: "error", message: "Failed to rename project." });
    });
  }, [
    renamingTitle,
    titleDraft,
    currentProjectId,
    currentProjectDetails?.project?.name,
    renameProject,
    setPopup,
  ]);

  const totalFiles = visibleFiles.length;
  const displayFileCount = totalFiles > 100 ? "100+" : String(totalFiles);

  const handleUploadChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
      if (!files || files.length === 0) return;
      await handleUploadFiles(Array.from(files));
      e.target.value = "";
    },
    [handleUploadFiles]
  );

  // Nested dropzone for drag-and-drop within ProjectContextPanel
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    noClick: true,
    noKeyboard: true,
    multiple: true,
    noDragEventsBubbling: true,
    onDrop: (acceptedFiles) => {
      void handleUploadFiles(acceptedFiles);
    },
  });

  if (!currentProjectId) return null; // no selection yet

  return (
    <div className="flex flex-col gap-6 w-full max-w-[800px] mx-auto mt-10 mb-[1.5rem]">
      <div
        className="flex items-center gap-2 text-text-04"
        onMouseEnter={() => {
          if (editIconHideRef.current)
            window.clearTimeout(editIconHideRef.current);
          setShowEditIcon(true);
        }}
        onMouseLeave={() => {
          if (editIconHideRef.current)
            window.clearTimeout(editIconHideRef.current);
          editIconHideRef.current = window.setTimeout(() => {
            setShowEditIcon(false);
          }, 250);
        }}
      >
        <SvgFolderOpen className="h-8 w-8 text-text-04 shrink-0" />
        {!renamingTitle ? (
          <div className="group flex items-center gap-2 min-w-0">
            <Text headingH2 className="font-heading-h2 truncate">
              {currentProjectDetails?.project?.name ??
                (projects || []).find((p) => p.id === currentProjectId)?.name ??
                ""}
            </Text>
            {!!currentProjectId && (
              <IconButton
                internal
                icon={SvgEditBig}
                tooltip="Rename project"
                className={`transition-opacity duration-150 shrink-0 ${
                  showEditIcon ? "opacity-100" : "opacity-0"
                }`}
                iconClassName="h-6 w-6"
                onFocus={() => {
                  if (editIconHideRef.current)
                    window.clearTimeout(editIconHideRef.current);
                  setShowEditIcon(true);
                }}
                onBlur={() => {
                  if (editIconHideRef.current)
                    window.clearTimeout(editIconHideRef.current);
                  editIconHideRef.current = window.setTimeout(() => {
                    setShowEditIcon(false);
                  }, 250);
                }}
                onClick={startRenamingTitle}
              />
            )}
          </div>
        ) : (
          <input
            ref={titleInputRef}
            value={titleDraft}
            onChange={(e) => setTitleDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                void commitRenameTitle();
              } else if (e.key === "Escape") {
                e.preventDefault();
                setRenamingTitle(false);
              }
            }}
            onBlur={() => void commitRenameTitle()}
            className="w-auto flex-1 bg-transparent outline-none border-b border-border-01 focus:border-text-04 font-heading-h2 text-text-04"
          />
        )}
      </div>

      <Separator className="my-0" />
      <div className="flex flex-row gap-2 justify-between">
        <div className="min-w-0">
          <Text headingH3 text04>
            Instructions
          </Text>
          {currentProjectDetails?.project?.instructions ? (
            <Text text02 secondaryBody className="truncate">
              {currentProjectDetails.project.instructions}
            </Text>
          ) : (
            <Text text02 secondaryBody className="truncate">
              Add instructions to tailor the response in this project.
            </Text>
          )}
        </div>
        <Button
          onClick={() => toggleModal(ModalIds.AddInstructionModal, true)}
          tertiary
        >
          <div className="flex flex-row gap-1 items-center">
            <SvgAddLines className="h-4 w-4 stroke-text-03" />
            <Text text03 mainUiAction className="whitespace-nowrap">
              Set Instructions
            </Text>
          </div>
        </Button>
      </div>
      <div
        className="flex flex-col gap-2 "
        {...getRootProps({ onClick: (e) => e.stopPropagation() })}
      >
        <div className="flex flex-row gap-2 justify-between">
          <div>
            <Text headingH3 text04>
              Files
            </Text>

            <Text text02 secondaryBody>
              Chats in this project can access these files.
            </Text>
          </div>
          <FilePicker
            trigger={
              <LineItem icon={SvgPlusCircle}>
                <Text text03 mainUiAction>
                  Add Files
                </Text>
              </LineItem>
            }
            recentFiles={recentFiles}
            onFileClick={handleFileClick}
            onPickRecent={async (file) => {
              if (!currentProjectId || !linkFileToProject) return;
              // Add a pending tile immediately with processing state
              setPendingLinkedFiles((prev) => {
                const pending: ProjectFile = {
                  ...file,
                  status: UserFileStatus.PROCESSING,
                };
                const map = new Map(prev.map((f) => [f.id, f]));
                map.set(file.id, pending);
                return Array.from(map.values());
              });
              // Ensure it appears on the left immediately
              markRecentlyAdded([file.id]);
              try {
                await linkFileToProject(currentProjectId, file.id);
                // The refresh inside linkFileToProject will populate real file; clear pending entry
                setPendingLinkedFiles((prev) =>
                  prev.filter((f) => f.id !== file.id)
                );
              } catch (e) {
                // Remove pending and notify
                setPendingLinkedFiles((prev) =>
                  prev.filter((f) => f.id !== file.id)
                );
                unmarkRecentlyAdded(file.id);
                setPopup({
                  type: "error",
                  message: `Failed to add ${file.name} to project`,
                });
              }
            }}
            onUnpickRecent={async (file) => {
              if (!currentProjectId) return;
              // If user unpicks before closing, ensure pending state is cleared
              setPendingLinkedFiles((prev) =>
                prev.filter((f) => f.id !== file.id)
              );
              // Optimistically remove without waiting on backend
              void removeFileOptimistic(file.id);
              unmarkRecentlyAdded(file.id);
            }}
            handleUploadChange={handleUploadChange}
            className="mr-1.5"
            selectedFileIds={(currentProjectDetails?.files || []).map(
              (f) => f.id
            )}
          />
        </div>
        {/* Hidden input just to satisfy dropzone contract; we rely on FilePicker for clicks */}
        <input {...getInputProps()} />

        {visibleFiles.length > 0 ? (
          <>
            {/* Mobile / small screens: just show a button to view files */}
            <div className="sm:hidden">
              <button
                className="w-full rounded-xl px-3 py-3 text-left bg-transparent hover:bg-accent-background-hovered hover:dark:bg-neutral-800/75 transition-colors"
                onClick={() => toggleModal(ModalIds.ProjectFilesModal, true)}
              >
                <div className="flex flex-col overflow-hidden">
                  <div className="flex items-center justify-between gap-2 w-full">
                    <Text text04 secondaryAction>
                      View files
                    </Text>
                    <SvgFiles className="h-5 w-5 stroke-text-02" />
                  </div>
                  <Text text03 secondaryBody>
                    {displayFileCount} files
                  </Text>
                </div>
              </button>
            </div>

            {/* Desktop / larger screens: show previews with optional View All */}
            <div className="hidden sm:flex gap-spacing-inline relative">
              {visibleFiles.slice(0, 4).map((f) => (
                <div key={f.id} className="w-40">
                  <FileCard
                    file={f}
                    removeFile={(fileId: string) => {
                      void removeFileOptimistic(fileId);
                    }}
                    onFileClick={handleFileClick}
                    isAttaching={pendingIds.has(f.id)}
                  />
                </div>
              ))}
              {totalFiles > 4 && (
                <button
                  className="rounded-xl px-3 py-1 text-left transition-colors hover:bg-background-tint-02"
                  onClick={() => toggleModal(ModalIds.ProjectFilesModal, true)}
                >
                  <div className="flex flex-col overflow-hidden h-12 p-1">
                    <div className="flex items-center justify-between gap-2 w-full">
                      <Text text04 secondaryAction>
                        View All
                      </Text>
                      <SvgFiles className="h-5 w-5 stroke-text-02" />
                    </div>
                    <Text text03 secondaryBody>
                      {displayFileCount} files
                    </Text>
                  </div>
                </button>
              )}
              {isDragActive && (
                <div className="pointer-events-none absolute inset-0 rounded-lg border-2 border-dashed border-action-link-05" />
              )}
            </div>
            {projectTokenCount > availableContextTokens && (
              <Text text02 secondaryBody>
                This project exceeds the model&apos;s context limits. Sessions
                will automatically search for relevant files first before
                generating response.
              </Text>
            )}
          </>
        ) : (
          <div
            className={`h-12 rounded-lg border border-dashed ${
              isDragActive
                ? "bg-action-link-01 border-action-link-05"
                : "border-border-01"
            } flex items-center pl-spacing-interline`}
          >
            <p
              className={`font-secondary-body ${
                isDragActive ? "text-action-link-05" : "text-text-02 "
              }`}
            >
              {isDragActive
                ? "Drop files here to add to this project"
                : "Add documents, texts, or images to use in the project. Drag & drop supported."}
            </p>
          </div>
        )}
      </div>

      <AddInstructionModal />

      {open && (
        <CoreModal
          className="w-[48rem] min-w-[48rem] max-w-[48rem] overflow-hidden"
          onClickOutside={onClose}
        >
          <UserFilesModalContent
            title="Project files"
            description="Sessions in this project can access the files here."
            icon={SvgFiles}
            recentFiles={visibleFiles}
            fixedHeight={588}
            onFileClick={handleFileClick}
            handleUploadChange={handleUploadChange}
            showRemove
            onRemove={async (file: ProjectFile) => {
              void removeFileOptimistic(file.id);
            }}
            onClose={onClose}
          />
        </CoreModal>
      )}
      {popup}
    </div>
  );
}
