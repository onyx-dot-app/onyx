"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import { FileIcon, Loader2, X } from "lucide-react";
import { Separator } from "@/components/ui/separator";
import { RiPlayListAddFill } from "react-icons/ri";
import { useProjectsContext } from "../../projects/ProjectsContext";
import FilePicker from "../files/FilePicker";
import FilesList from "../files/FilesList";
import type {
  ProjectFile,
  CategorizedFiles,
} from "../../projects/projectsService";
import { UserFileStatus } from "../../projects/projectsService";
import { ChatFileType } from "@/app/chat/interfaces";
import { usePopup } from "@/components/admin/connectors/Popup";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import {
  MultipleFilesIcon,
  OpenFolderIcon,
  ListSettingsIcon,
  DocumentIcon,
} from "@/components/icons/CustomIcons";

export function FileCard({
  file,
  removeFile,
  hideProcessingState = false,
  onFileClick,
}: {
  file: ProjectFile;
  removeFile: (fileId: string) => void;
  hideProcessingState?: boolean;
  onFileClick?: (file: ProjectFile) => void;
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
    String(file.status).toLowerCase() === "processing" ||
    String(file.status).toLowerCase() === "uploading";

  // When hideProcessingState is true, we treat processing files as completed for display purposes
  const isProcessing = hideProcessingState ? false : isActuallyProcessing;

  const handleRemoveFile = async (e: React.MouseEvent) => {
    e.stopPropagation();
    // Allow removal if hideProcessingState is true (within context limits) or if not actually processing
    if (isActuallyProcessing && !hideProcessingState) return;
    removeFile(file.id);
  };

  return (
    <div
      className={`relative group flex items-center gap-3 border border-border rounded-xl ${
        isProcessing ? "bg-accent-background" : "bg-background-background"
      } px-3 py-1 shadow-sm h-14 w-52 ${
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
      {!isProcessing && (
        <button
          onClick={handleRemoveFile}
          title="Delete file"
          aria-label="Delete file"
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-[#1f1f1f] text-white dark:bg-[#fefcfa] dark:text-black shadow-sm opacity-0 group-hover:opacity-100 focus:opacity-100 pointer-events-none group-hover:pointer-events-auto focus:pointer-events-auto transition-opacity duration-150 hover:opacity-90"
        >
          <X className="h-4 w-4 dark:text-dark-tremor-background-muted" />
        </button>
      )}
      <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-transparent">
        {isProcessing ? (
          <Loader2 className="h-5 w-5 text-onyx-muted animate-spin" />
        ) : (
          <div className="bg-accent-background p-2 rounded-lg shadow-sm">
            <DocumentIcon className="h-5 w-5 text-onyx-muted" />
          </div>
        )}
      </div>
      <div className="flex flex-col overflow-hidden">
        <span className="text-onyx-medium text-sm truncate" title={file.name}>
          {file.name}
        </span>
        <span className="text-onyx-muted text-xs truncate">
          {isProcessing
            ? file.status === UserFileStatus.UPLOADING
              ? "Uploading..."
              : "Processing..."
            : typeLabel}
        </span>
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
  const [isInstrOpen, setIsInstrOpen] = useState(false);
  const [showProjectFiles, setShowProjectFiles] = useState(false);
  const [instructionText, setInstructionText] = useState("");
  const { popup, setPopup } = usePopup();
  const [tempProjectFiles, setTempProjectFiles] = useState<ProjectFile[]>([]);

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
    upsertInstructions,
    currentProjectDetails,
    currentProjectId,
    uploadFiles,
    recentFiles,
    unlinkFileFromProject,
    linkFileToProject,
  } = useProjectsContext();
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    const preset = currentProjectDetails?.project?.instructions ?? "";
    setInstructionText(preset);
  }, [currentProjectDetails?.project?.instructions ?? ""]);

  const totalFiles = (currentProjectDetails?.files || []).length;
  const displayFileCount = totalFiles > 100 ? "100+" : String(totalFiles);

  const handleUploadChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files;
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
        // Replace temp entries with backend entries (by index) so keys become backend IDs. This will prevent flickering.
        setTempProjectFiles((prev) => [
          ...prev.slice(0, -tempFiles.length),
          ...result.user_files,
        ]);
        const unsupported = result?.unsupported_files || [];
        const nonAccepted = result?.non_accepted_files || [];
        if (unsupported.length > 0 || nonAccepted.length > 0) {
          const parts: string[] = [];
          if (unsupported.length > 0) {
            parts.push(`Unsupported: ${unsupported.join(", ")}`);
          }
          if (nonAccepted.length > 0) {
            parts.push(`Not accepted: ${nonAccepted.join(", ")}`);
          }
          setPopup({
            type: "warning",
            message: `Some files were not uploaded. ${parts.join(" | ")}`,
          });
        }
      } finally {
        setIsUploading(false);
        setTempProjectFiles([]);
        e.target.value = "";
      }
    },
    [currentProjectId, uploadFiles, setPopup]
  );

  if (!currentProjectId) return null; // no selection yet

  return (
    <div className="flex flex-col gap-5 p-4 w-full max-w-[800px] mx-auto mt-10">
      <div className="flex flex-col gap-2">
        <OpenFolderIcon size={34} className="text-onyx-ultra-strong" />
        <h1 className="text-onyx-strong text-4xl">
          {currentProjectDetails?.project?.name || "Loading project..."}
        </h1>
      </div>

      <Separator className="my-0" />
      <div className="flex flex-row gap-2 justify-between">
        <div className="min-w-0">
          <p className="text-onyx-medium text-2xl">Instructions</p>
          {currentProjectDetails?.project?.instructions ? (
            <p
              className="text-onyx-muted text-base truncate"
              title={currentProjectDetails.project.instructions || ""}
            >
              {currentProjectDetails.project.instructions}
            </p>
          ) : (
            <p className="text-onyx-muted text-base truncate">
              Add instructions to tailor the response in this project.
            </p>
          )}
        </div>
        <button
          onClick={() => setIsInstrOpen(true)}
          className="flex flex-row gap-2 items-center justify-center p-2 rounded-md bg-background-dark/75 hover:dark:bg-neutral-800/75 hover:bg-accent-background-hovered cursor-pointer transition-all duration-150 shrink-0 whitespace-nowrap h-12"
        >
          <ListSettingsIcon size={20} className="text-onyx-emphasis" />
          <p className="text-onyx-emphasis text-lg whitespace-nowrap">
            Set Instructions
          </p>
        </button>
      </div>
      <div className="flex flex-col gap-2">
        <div className="flex flex-row gap-2 justify-between">
          <div>
            <p className="text-onyx-medium text-2xl">Files</p>

            <p className="text-onyx-muted text-base">
              Chats in this project can access these files.
            </p>
          </div>
          <FilePicker
            showTriggerLabel
            triggerLabel="Add Files"
            recentFiles={recentFiles}
            onFileClick={handleFileClick}
            onPickRecent={async (file) => {
              if (!currentProjectId) return;
              if (!linkFileToProject) return;
              await linkFileToProject(currentProjectId, file.id);
            }}
            handleUploadChange={handleUploadChange}
            triggerLabelClassName="text-lg text-onyx-emphasis"
            triggerClassName="h-12"
          />
        </div>

        {tempProjectFiles.length > 0 ||
        (currentProjectDetails?.files &&
          currentProjectDetails.files.length > 0) ? (
          <>
            {/* Mobile / small screens: just show a button to view files */}
            <div className="sm:hidden">
              <button
                className="w-full rounded-xl px-3 py-3 text-left bg-transparent hover:bg-accent-background-hovered hover:dark:bg-neutral-800/75 transition-colors"
                onClick={() => setShowProjectFiles(true)}
              >
                <div className="flex flex-col overflow-hidden">
                  <div className="flex items-center justify-between gap-2 w-full">
                    <span className="text-onyx-medium text-sm truncate flex-1">
                      View files
                    </span>
                    <MultipleFilesIcon className="h-5 w-5 text-onyx-medium" />
                  </div>
                  <span className="text-onyx-muted text-sm">
                    {displayFileCount} files
                  </span>
                </div>
              </button>
            </div>

            {/* Desktop / larger screens: show previews with optional View All */}
            <div className="hidden sm:flex gap-3">
              {(() => {
                const byId = new Map<string, ProjectFile>();
                // Prefer backend files when available
                (currentProjectDetails?.files || []).forEach((f) =>
                  byId.set(f.id, f)
                );
                // Add temp files only if a backend file with same id doesn't exist yet
                tempProjectFiles.forEach((f) => {
                  if (!byId.has(f.id)) byId.set(f.id, f);
                });
                return Array.from(byId.values())
                  .slice(0, 3)
                  .map((f) => (
                    <div key={f.id} className="w-52">
                      <FileCard
                        file={f}
                        removeFile={async (fileId: string) => {
                          if (!currentProjectId) return;
                          await unlinkFileFromProject(currentProjectId, fileId);
                        }}
                        onFileClick={handleFileClick}
                      />
                    </div>
                  ));
              })()}
              {totalFiles > 3 && (
                <button
                  className="rounded-xl px-3 py-1 text-left bg-transparent hover:bg-accent-background-hovered hover:dark:bg-neutral-800/75 transition-colors"
                  onClick={() => setShowProjectFiles(true)}
                >
                  <div className="flex flex-col overflow-hidden h-12 p-1">
                    <div className="flex items-center justify-between gap-2 w-full">
                      <span className="text-onyx-medium text-sm truncate flex-1">
                        View All
                      </span>
                      <MultipleFilesIcon className="h-5 w-5 text-onyx-medium" />
                    </div>
                    <span className="text-onyx-muted text-sm">
                      {displayFileCount} files
                    </span>
                  </div>
                </button>
              )}
            </div>
            {projectTokenCount > availableContextTokens && (
              <p className="text-onyx-muted text-base">
                This project exceeds the model&apos;s context limits. Sessions
                will automatically search for relevant files first before
                generating response.
              </p>
            )}
          </>
        ) : (
          <p className="text-onyx-muted text-base">No files yet.</p>
        )}
      </div>

      <Dialog open={isInstrOpen} onOpenChange={setIsInstrOpen}>
        <DialogContent className="w-[95%] max-w-2xl">
          <DialogHeader>
            <div className="flex flex-col gap-3">
              <ListSettingsIcon size={22} />
              <DialogTitle>Set Project Instructions</DialogTitle>
            </div>
            <DialogDescription>
              Instruct specific behaviors, focus, tones, or formats for the
              response in this project.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <Textarea
              value={instructionText}
              onChange={(e) => setInstructionText(e.target.value)}
              placeholder="Think step by step and show reasoning for complex problems. Use specific examples."
              className="min-h-[140px]"
            />
            <div className="flex justify-end gap-4">
              <Button variant="outline" onClick={() => setIsInstrOpen(false)}>
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setIsInstrOpen(false);
                  upsertInstructions(instructionText);
                }}
              >
                Save Instructions
              </Button>
            </div>
          </div>
        </DialogContent>
      </Dialog>
      <Dialog open={showProjectFiles} onOpenChange={setShowProjectFiles}>
        <DialogContent
          className="w-full max-w-lg focus:outline-none focus-visible:outline-none"
          tabIndex={-1}
          onOpenAutoFocus={(e) => {
            // Prevent auto-focus which can interfere with input
            e.preventDefault();
          }}
        >
          <DialogHeader>
            <MultipleFilesIcon className="h-8 w-8 text-onyx-ultra-strong" />
            <DialogTitle>Project files</DialogTitle>
            <DialogDescription>
              Sessions in this project can access the files here.
            </DialogDescription>
          </DialogHeader>
          <FilesList
            recentFiles={(currentProjectDetails?.files || []) as any}
            handleUploadChange={handleUploadChange}
            showRemove
            onRemove={async (file) => {
              if (!currentProjectId) return;
              await unlinkFileFromProject(currentProjectId, file.id);
            }}
            onFileClick={handleFileClick}
          />
        </DialogContent>
      </Dialog>
      {popup}
    </div>
  );
}
