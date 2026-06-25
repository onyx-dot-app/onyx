"use client";

import React, { useCallback } from "react";
import { useTranslation } from "react-i18next";
import { useDropzone } from "react-dropzone";
import { useProjectsContext } from "@/providers/ProjectsContext";
import FilePickerPopover from "@/refresh-components/popovers/FilePickerPopover";
import {
  UserFileStatus,
  type ProjectFile,
} from "@/app/app/projects/projectsService";
import { MinimalOnyxDocument } from "@/lib/search/interfaces";
import { Button, Divider, LineItemButton, Text } from "@opal/components";
import { Content, ContentAction } from "@opal/layouts";
import AddInstructionModal from "@/sections/modals/AddInstructionModal";
import UserFilesModal from "@/sections/modals/UserFilesModal";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { FileCard } from "@/sections/cards/FileCard";
import { hasNonImageFiles } from "@/lib/utils";
import { cn } from "@opal/utils";
import {
  SvgAddLines,
  SvgFiles,
  SvgFolderOpen,
  SvgPlusCircle,
  SvgSimpleLoader,
} from "@opal/icons";

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
  const { t } = useTranslation();
  const addInstructionModal = useCreateModal();
  const projectFilesModal = useCreateModal();
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
      beginUpload(Array.from(files), currentProjectId);
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

  const currentProject = projects.find((p) => p.id === currentProjectId);
  const projectName = currentProject?.name || t("projects.loading_project");

  if (!currentProjectId) return null; // no selection yet

  // Detect if there are any non-image files in the displayed files
  // to determine if images should be compact
  const displayedFiles = allCurrentProjectFiles.slice(0, 4);
  const shouldCompactImages = hasNonImageFiles(displayedFiles);

  return (
    <>
      <addInstructionModal.Provider>
        <AddInstructionModal />
      </addInstructionModal.Provider>

      <projectFilesModal.Provider>
        <UserFilesModal
          title={t("projects.project_files_title")}
          description={t("projects.project_files_desc")}
          recentFiles={[...allCurrentProjectFiles]}
          onView={handleOnView}
          handleUploadChange={handleUploadChange}
          onDelete={async (file: ProjectFile) => {
            if (!currentProjectId) return;
            await unlinkFileFromProject(currentProjectId, file.id);
          }}
        />
      </projectFilesModal.Provider>

      <div className="w-(--app-page-main-content-width) mx-auto flex flex-col gap-6 pb-6">
        <Content
          icon={SvgFolderOpen}
          title={projectName}
          editable
          onTitleChange={async (newName) => {
            if (currentProjectId) {
              await renameProject(currentProjectId, newName);
            }
          }}
        />

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        <ContentAction
          sizePreset="main-ui"
          variant="section"
          title={t("projects.instructions")}
          description={
            isLoadingProjectDetails && !currentProjectDetails
              ? undefined
              : currentProjectDetails?.project?.instructions ||
                t("projects.instructions_desc_empty")
          }
          descriptionMaxLines={2}
          padding="fit"
          center
          rightChildren={
            <Button
              prominence="tertiary"
              icon={SvgAddLines}
              onClick={() => addInstructionModal.toggle(true)}
              interaction={addInstructionModal.isOpen ? "active" : undefined}
            >
              {t("projects.set_instructions")}
            </Button>
          }
        />

        <div
          className="flex flex-col gap-2 pb-2"
          {...getRootProps({ onClick: (e) => e.stopPropagation() })}
        >
          <ContentAction
            sizePreset="main-ui"
            variant="section"
            title={t("projects.files")}
            description={t("projects.files_desc")}
            padding="fit"
            center
            rightChildren={
              <FilePickerPopover
                trigger={(open) => (
                  <Button
                    icon={SvgPlusCircle}
                    prominence="tertiary"
                    interaction={open ? "active" : undefined}
                  >
                    {t("projects.add_files")}
                  </Button>
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
                selectedFileIds={(allCurrentProjectFiles || []).map(
                  (f) => f.id
                )}
              />
            }
          />

          {/* Hidden input just to satisfy dropzone contract; we rely on FilePicker for clicks */}
          <input {...getInputProps()} />

          {isLoadingProjectDetails && !currentProjectDetails ? (
            <SvgSimpleLoader />
          ) : allCurrentProjectFiles.length > 0 ? (
            <>
              {/* Mobile / small screens: just show a button to view files */}
              <div className="sm:hidden">
                <LineItemButton
                  sizePreset="main-ui"
                  variant="section"
                  title={t("projects.view_files")}
                  description={t("projects.files_count", {
                    count: displayFileCount,
                  })}
                  icon={SvgFiles}
                  width="full"
                  onClick={() => projectFilesModal.toggle(true)}
                />
              </div>

              {/* Desktop / larger screens: show previews with optional View All */}
              <div className="hidden sm:flex gap-1 relative items-center">
                {allCurrentProjectFiles.slice(0, 4).map((f) => (
                  <FileCard
                    key={f.id}
                    file={f}
                    removeFile={async (fileId: string) => {
                      if (!currentProjectId) return;
                      await unlinkFileFromProject(currentProjectId, fileId);
                    }}
                    onFileClick={handleOnView}
                    compactImages={shouldCompactImages}
                  />
                ))}

                {totalFiles > 4 && (
                  <LineItemButton
                    sizePreset="main-ui"
                    variant="section"
                    title={t("projects.view_all")}
                    description={t("projects.files_count", {
                      count: displayFileCount,
                    })}
                    rightChildren={
                      <SvgFiles className="h-5 w-5 stroke-text-02" />
                    }
                    onClick={() => projectFilesModal.toggle(true)}
                  />
                )}
                {isDragActive && (
                  <div className="pointer-events-none absolute inset-0 rounded-lg border-2 border-dashed border-action-link-05" />
                )}
              </div>

              {projectTokenCount > availableContextTokens && (
                <Text as="p" font="secondary-body" color="text-02">
                  {t("projects.context_limit_warning")}
                </Text>
              )}
            </>
          ) : (
            <div
              className={cn(
                "h-12 rounded-xl border border-dashed flex items-center pl-2",
                isDragActive
                  ? "bg-action-link-01 border-action-link-05 text-action-link-05"
                  : "border-border-01 text-text-02"
              )}
            >
              <Text as="p" font="secondary-body" color="inherit">
                {isDragActive
                  ? t("projects.dropzone_active")
                  : t("projects.dropzone_desc")}
              </Text>
            </div>
          )}
        </div>
      </div>
    </>
  );
}
