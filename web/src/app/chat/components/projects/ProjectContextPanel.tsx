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
import { FileIcon, FolderOpen, Loader2, X } from "lucide-react";
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

export function FileCard({ file }: { file: ProjectFile }) {
  const { deleteUserFile } = useProjectsContext();
  const typeLabel = useMemo(() => {
    if (!file.file_type) return "";
    const parts = String(file.file_type).split("/");
    const ext = parts[parts.length - 1] || file.file_type;
    return String(ext).toUpperCase();
  }, [file.file_type]);

  const isProcessing =
    String(file.status).toLowerCase() === "processing" ||
    String(file.status).toLowerCase() === "uploading";

  const handleDelete = async (e: React.MouseEvent) => {
    e.stopPropagation();
    if (isProcessing) return;
    try {
      await deleteUserFile(file.id);
    } catch (err) {
      // Swallow; parent poll/refresh will sync state
    }
  };

  return (
    <div className="relative flex items-center gap-3 border border-border rounded-xl bg-background-background px-3 py-2 shadow-sm">
      {!isProcessing && (
        <button
          onClick={handleDelete}
          title="Delete file"
          aria-label="Delete file"
          className="absolute -left-2 -top-2 z-10 h-5 w-5 flex items-center justify-center rounded-[4px] border border-border text-[11px] bg-[#1f1f1f] text-white dark:bg-[#fefcfa] dark:text-black shadow-sm hover:opacity-90"
        >
          <X className="h-4 w-4 dark:text-dark-tremor-background-muted" />
        </button>
      )}
      <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-background-dark/60">
        {isProcessing ? (
          <Loader2 className="h-5 w-5 text-text-400 animate-spin" />
        ) : (
          <FileIcon className="h-5 w-5 text-text-400" />
        )}
      </div>
      <div className="flex flex-col overflow-hidden">
        <span
          className="text-sm font-medium text-text-darker truncate"
          title={file.name}
        >
          {file.name}
        </span>
        <span className="text-xs text-text-400 truncate">
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

export default function ProjectContextPanel() {
  const [isInstrOpen, setIsInstrOpen] = useState(false);
  const [showProjectFiles, setShowProjectFiles] = useState(false);
  const [instructionText, setInstructionText] = useState("");
  const { popup, setPopup } = usePopup();
  const [tempProjectFiles, setTempProjectFiles] = useState<ProjectFile[]>([]);
  const {
    upsertInstructions,
    currentProjectDetails,
    currentProjectId,
    uploadFiles,
    recentFiles,
  } = useProjectsContext();
  const [isUploading, setIsUploading] = useState(false);

  useEffect(() => {
    const preset = currentProjectDetails?.instructions?.system_prompt ?? "";
    setInstructionText(preset);
  }, [currentProjectDetails?.instructions?.system_prompt ?? ""]);

  if (!currentProjectId) return null; // no selection yet

  return (
    <div className="flex flex-col gap-2 p-4 w-[800px] mx-auto mt-10">
      <FolderOpen size={34} />
      <h1 className="text-4xl font-medium">
        {currentProjectDetails?.project?.name || "Loading project..."}
      </h1>
      <Separator />
      <div className="flex flex-row gap-2 justify-between">
        <div className="min-w-0">
          <p className="font-bold">Instructions</p>
          {currentProjectDetails?.instructions ? (
            <p
              className="font-light truncate"
              title={currentProjectDetails.instructions.system_prompt}
            >
              {currentProjectDetails.instructions.system_prompt}
            </p>
          ) : (
            <p className="font-light truncate">
              Add instructions to tailor the response in this project.
            </p>
          )}
        </div>
        <button
          onClick={() => setIsInstrOpen(true)}
          className="flex flex-row gap-2 items-center justify-center p-2 rounded-md bg-background-dark/75 hover:dark:bg-neutral-800/75 hover:bg-accent-background-hovered cursor-pointer transition-all duration-150 shrink-0 whitespace-nowrap"
        >
          <RiPlayListAddFill
            size={20}
            className="text-text-darker dark:text-text-lighter"
          />
          <p className="text-sm text-text-darker dark:text-text-lighter whitespace-nowrap">
            Set Instructions
          </p>
        </button>
      </div>
      <div className="flex flex-row gap-2 justify-between">
        <div>
          <p className="font-bold">Files</p>

          <p className="font-light">
            Chats in this project can access these files.
          </p>
        </div>
        <FilePicker
          showTriggerLabel
          triggerLabel="Add Files"
          recentFiles={recentFiles}
          handleUploadChange={async (
            e: React.ChangeEvent<HTMLInputElement>
          ) => {
            const files = e.target.files;
            if (!files || files.length === 0) return;
            setIsUploading(true);
            try {
              // Show temporary uploading files immediately
              const tempFiles: ProjectFile[] = Array.from(files).map(
                (file) => ({
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
                })
              );
              setTempProjectFiles((prev) => [...prev, ...tempFiles]);

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
          }}
        />
      </div>

      {tempProjectFiles.length > 0 ||
      (currentProjectDetails?.files &&
        currentProjectDetails.files.length > 0) ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
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
              .map((f) => <FileCard key={f.id} file={f} />);
          })()}
          {[...(currentProjectDetails?.files || [])].length > 3 && (
            <button
              className="flex items-center gap-3 border border-border rounded-xl bg-background-background px-3 py-2 shadow-sm text-left"
              onClick={() => setShowProjectFiles(true)}
            >
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-background-dark/60">
                <FileIcon className="h-5 w-5 text-text-400" />
              </div>
              <div className="flex flex-col overflow-hidden">
                <span className="text-sm font-medium text-text-darker truncate">
                  View all project files
                </span>
                <span className="text-xs text-text-400 truncate">
                  {(currentProjectDetails?.files || []).length} files
                </span>
              </div>
            </button>
          )}
        </div>
      ) : (
        <p className="text-sm text-text-400">No files yet.</p>
      )}

      <Dialog open={isInstrOpen} onOpenChange={setIsInstrOpen}>
        <DialogContent className="w-[95%] max-w-2xl">
          <DialogHeader>
            <div className="flex flex-col gap-3">
              <RiPlayListAddFill size={22} />
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
        <DialogContent className="w-full max-w-lg">
          <DialogHeader>
            <FolderOpen size={32} />
            <DialogTitle>Project files</DialogTitle>
          </DialogHeader>
          <FilesList
            recentFiles={(currentProjectDetails?.files || []) as any}
          />
        </DialogContent>
      </Dialog>
      {popup}
    </div>
  );
}
