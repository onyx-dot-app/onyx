"use client";

import React, { useCallback, useMemo, useState } from "react";
import { useDropzone } from "react-dropzone";
import Separator from "@/refresh-components/Separator";
import { useProjectsContext } from "../../projects/ProjectsContext";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import type { ProjectFile } from "../../projects/projectsService";
import { usePopup } from "@/components/admin/connectors/Popup";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import Button from "@/refresh-components/buttons/Button";

import AddInstructionModal from "@/components/modals/AddInstructionModal";
import UserFilesModal from "@/components/modals/UserFilesModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import Text from "@/refresh-components/texts/Text";
import CreateButton from "@/refresh-components/buttons/CreateButton";
import { FileCard } from "../input/FileCard";
import { hasNonImageFiles } from "@/lib/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import { FileCardSkeleton } from "@/app/chat/components/input/FileCard";
import ButtonRenaming from "@/refresh-components/buttons/ButtonRenaming";
import { UserFileStatus } from "../../projects/projectsService";
import { SvgAddLines, SvgEdit, SvgFiles, SvgFolderOpen } from "@opal/icons";
export interface ProjectContextPanelProps {
  projectTokenCount?: number;
  availableContextTokens?: number;
  setPresentingDocument?: (document: MinimalOnyxDocument) => void;
}
export default function ProjectContextPanel({
  projectTokenCount = 0,
  availableContextTokens = 128_000,
  setPresentingDocument,
}: ProjectContextPanelProps) {
  const { popup, setPopup } = usePopup();

  const addInstructionModal = useCreateModal();
  const projectFilesModal = useCreateModal();
  // Edit project name state
  const [isEditingName, setIsEditingName] = useState(false);
  // Convert ProjectFile to MinimalOnyxDocument format for viewing
  const handleOnView = useCallback(
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
    unlinkFileFromProject,
    linkFileToProject,
    allCurrentProjectFiles,
    isLoadingProjectDetails,
    beginUpload,
    projects,
    renameProject,
  } = useProjectsContext();
  const handleUploadFiles = useCallback(
    async (files: File[]) => {
      if (!files || files.length === 0) return;
      beginUpload(Array.from(files), currentProjectId, setPopup);
    },
    [currentProjectId, beginUpload]
  );

  const totalFiles = allCurrentProjectFiles.length;
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

  // Handle project name editing
  const currentProject = projects.find((p) => p.id === currentProjectId);
  const projectName = currentProject?.name || "Loading project...";

  const startEditing = useCallback(() => {
    setIsEditingName(true);
  }, []);

  const cancelEditing = useCallback(() => {
    setIsEditingName(false);
  }, []);

  if (!currentProjectId) return null; // no selection yet

  // Detect if there are any non-image files in the displayed files
  // to determine if images should be compact
  const displayedFiles = allCurrentProjectFiles.slice(0, 4);
  const shouldCompactImages = hasNonImageFiles(displayedFiles);

  return (
    <>
      {popup}

      <addInstructionModal.Provider>
        <AddInstructionModal />
      </addInstructionModal.Provider>

      <projectFilesModal.Provider>
        <UserFilesModal
          title="Project Files"
          description="Sessions in this project can access the files here."
          recentFiles={[...allCurrentProjectFiles]}
          onView={handleOnView}
          handleUploadChange={handleUploadChange}
          onDelete={async (file: ProjectFile) => {
            if (!currentProjectId) return;
            await unlinkFileFromProject(currentProjectId, file.id);
          }}
        />
      </projectFilesModal.Provider>
      <div className="flex flex-col gap-6 w-full max-w-[min(50rem,100%)] mx-auto p-4 pt-14 pb-6">
        <div className="flex flex-col gap-1 text-text-04">
          <SvgFolderOpen className="h-8 w-8 text-text-04" />
          <div className="group flex items-center gap-2">
            {isEditingName ? (
              <ButtonRenaming
                initialName={projectName}
                onRename={async (newName) => {
                  if (currentProjectId) {
                    await renameProject(currentProjectId, newName);
                  }
                }}
                onClose={cancelEditing}
                className="font-heading-h2 text-text-04"
              />
            ) : (
              <>
                <Text as="p" headingH2 className="font-heading-h2">
                  {projectName}
                </Text>
                <IconButton
                  icon={SvgEdit}
                  internal
                  onClick={startEditing}
                  className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
                  tooltip="Edit project name"
                />
              </>
            )}
          </div>
        </div>

        <Separator className="my-0" />
        <div className="flex flex-row gap-2 justify-between">
          <div className="min-w-0 flex-1">
            <Text as="p" headingH3 text04>
              Instructions
            </Text>
            {isLoadingProjectDetails && !currentProjectDetails ? (
              <div className="h-5 w-3/4 rounded bg-background-tint-02 animate-pulse" />
            ) : currentProjectDetails?.project?.instructions ? (
              <Text as="p" text02 secondaryBody className="truncate">
                {currentProjectDetails.project.instructions}
              </Text>
            ) : (
              <Text as="p" text02 secondaryBody className="truncate">
                Add instructions to tailor the response in this project.
              </Text>
            )}
          </div>
          <Button
            leftIcon={SvgAddLines}
            onClick={() => addInstructionModal.toggle(true)}
            tertiary
          >
            Set Instructions
          </Button>
        </div>
        <div
          className="flex flex-col gap-2 "
          {...getRootProps({ onClick: (e) => e.stopPropagation() })}
        >
          <div className="flex flex-row gap-2 justify-between">
            <div>
              <Text as="p" headingH3 text04>
                Files
              </Text>
              <Text as="p" text02 secondaryBody>
                Chats in this project can access these files.
              </Text>
            </div>
            <FilePickerPopover
              trigger={(open) => (
                // The `secondary={undefined}` is required here because `CreateButton` sets it to true.
                // Therefore, we need to first remove the truthiness before passing in the other `tertiary` flag.
                <CreateButton secondary={undefined} tertiary transient={open}>
                  Add Files
                </CreateButton>
              )}
              onFileClick={handleOnView}
              onPickRecent={async (file) => {
                if (file.status === UserFileStatus.UPLOADING) return;
                if (file.status === UserFileStatus.DELETING) return;
                if (!currentProjectId) return;
                if (!linkFileToProject) return;
                linkFileToProject(currentProjectId, file);
              }}
              onUnpickRecent={async (file) => {
                if (!currentProjectId) return;
                await unlinkFileFromProject(currentProjectId, file.id);
              }}
              handleUploadChange={handleUploadChange}
              selectedFileIds={(allCurrentProjectFiles || []).map((f) => f.id)}
            />
          </div>
          {/* Hidden input just to satisfy dropzone contract; we rely on FilePicker for clicks */}
          <input {...getInputProps()} />

          {isLoadingProjectDetails && !currentProjectDetails ? (
            <>
              {/* Mobile / small screens: show skeleton */}
              <div className="sm:hidden">
                <div className="w-full h-[68px] rounded-xl bg-background-tint-02 animate-pulse" />
              </div>

              {/* Desktop / larger screens: show skeleton file cards */}
              <div className="hidden sm:flex gap-1">
                <FileCardSkeleton />
                <FileCardSkeleton />
                <FileCardSkeleton />
                <FileCardSkeleton />
              </div>
            </>
          ) : allCurrentProjectFiles.length > 0 ? (
            <>
              {/* Mobile / small screens: just show a button to view files */}
              <div className="sm:hidden">
                <button
                  className="w-full rounded-xl px-3 py-3 text-left bg-transparent hover:bg-accent-background-hovered hover:dark:bg-neutral-800/75 transition-colors"
                  onClick={() => projectFilesModal.toggle(true)}
                >
                  <div className="flex flex-col overflow-hidden">
                    <div className="flex items-center justify-between gap-2 w-full">
                      <Text as="p" text04 secondaryAction>
                        View files
                      </Text>
                      <SvgFiles className="h-5 w-5 stroke-text-02" />
                    </div>
                    <Text as="p" text03 secondaryBody>
                      {displayFileCount} files
                    </Text>
                  </div>
                </button>
              </div>

              {/* Desktop / larger screens: show previews with optional View All */}
              <div className="hidden sm:flex gap-1 relative items-center">
                {(() => {
                  return allCurrentProjectFiles.slice(0, 4).map((f) => (
                    <div key={f.id}>
                      <FileCard
                        file={f}
                        removeFile={async (fileId: string) => {
                          if (!currentProjectId) return;
                          await unlinkFileFromProject(currentProjectId, fileId);
                        }}
                        onFileClick={handleOnView}
                        compactImages={shouldCompactImages}
                        className="w-40"
                      />
                    </div>
                  ));
                })()}
                {totalFiles > 4 && (
                  <button
                    className="rounded-xl px-3 py-1 text-left transition-colors hover:bg-background-tint-02"
                    onClick={() => projectFilesModal.toggle(true)}
                  >
                    <div className="flex flex-col overflow-hidden h-12 p-1">
                      <div className="flex items-center justify-between gap-2 w-full">
                        <Text as="p" text04 secondaryAction>
                          View All
                        </Text>
                        <SvgFiles className="h-5 w-5 stroke-text-02" />
                      </div>
                      <Text as="p" text03 secondaryBody>
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
                <Text as="p" text02 secondaryBody>
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
              } flex items-center pl-2`}
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
      </div>
    </>
  );
}
