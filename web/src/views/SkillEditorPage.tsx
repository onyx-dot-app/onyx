"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import useSWR, { useSWRConfig } from "swr";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import {
  Button,
  Card,
  CompactMarkdown,
  Divider,
  InputTextArea,
  InputTypeIn,
  MessageCard,
  Tag,
  Tooltip,
} from "@opal/components";
import {
  SvgAlertTriangle,
  SvgBlocks,
  SvgShare,
  SvgSimpleLoader,
  SvgTrash,
} from "@opal/icons";
import {
  Content,
  InputHorizontal,
  InputVertical,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  createCustomSkillFromEditor,
  deleteUserSkill,
  inspectSkillBundle,
  isSkillNameConflict,
  patchUserSkill,
  removeUserSkillFile,
  uploadUserSkillFiles,
} from "@/lib/skills/api";
import type { SkillEditableDetail } from "@/lib/skills/types";
import type { PreparedSkillFilesUpload } from "@/lib/skills/bundleUpload";
import {
  discardSkillCreationDraft,
  getSkillCreationDraft,
} from "@/lib/skills/creationDraft";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import InstructionsDisplayModeToggle, {
  type InstructionsDisplayMode,
} from "@/sections/skills/InstructionsDisplayModeToggle";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillNameConflictModal from "@/sections/modals/skills/SkillNameConflictModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import SkillFileTree from "@/sections/skills/SkillFileTree";
import SkillFilesPicker from "@/sections/skills/SkillFilesPicker";
import { ConfirmationModalLayout } from "@opal/layouts";

interface SkillEditorPageProps {
  skillId?: string;
  draftId?: string;
}

function getSharingStatus(skill: SkillEditableDetail): {
  title: string;
  description: string;
  color: "blue" | "gray" | "purple";
} {
  if (skill.public_permission !== null) {
    return {
      title: "Organization",
      description:
        skill.public_permission === "EDITOR"
          ? "Everyone in your organization can use and edit this skill."
          : "Everyone in your organization can use this skill.",
      color: "blue",
    };
  }

  const userCount = skill.user_shares.length;
  const groupCount = skill.group_shares.length;
  const shareCount = userCount + groupCount;
  if (shareCount > 0) {
    return {
      title: `${shareCount} ${shareCount === 1 ? "share" : "shares"}`,
      description: "Only selected users and groups can use this skill.",
      color: "gray",
    };
  }

  return {
    title: "Personal",
    description: "Only you can use this skill.",
    color: "purple",
  };
}

export default function SkillEditorPage({
  skillId,
  draftId,
}: SkillEditorPageProps) {
  const isCreating = skillId === undefined;
  const router = useRouter();
  const creationDraft = useMemo(
    () => (isCreating && draftId ? getSkillCreationDraft(draftId) : undefined),
    [draftId, isCreating]
  );
  const { mutate } = useSWRConfig();
  const {
    data: skill,
    error,
    isLoading,
    mutate: refreshSkill,
  } = useSWR<SkillEditableDetail>(
    skillId ? SWR_KEYS.editableSkill(skillId) : null,
    errorHandlingFetcher
  );

  const [name, setName] = useState(creationDraft?.contents.name ?? "");
  const [description, setDescription] = useState(
    creationDraft?.contents.description ?? ""
  );
  const [instructionsMarkdown, setInstructionsMarkdown] = useState(
    creationDraft?.contents.instructions_markdown ?? ""
  );
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("raw");
  const [hydratedSkillId, setHydratedSkillId] = useState<string | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isPreparingFiles, setIsPreparingFiles] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [pendingFilesUpload, setPendingFilesUpload] =
    useState<PreparedSkillFilesUpload | null>(creationDraft?.upload ?? null);
  const [filesUploadToConfirm, setFilesUploadToConfirm] =
    useState<PreparedSkillFilesUpload | null>(null);
  const [removingFilePath, setRemovingFilePath] = useState<string | null>(null);
  const [isDeleting, setIsDeleting] = useState(false);
  const [conflictingSkillName, setConflictingSkillName] = useState<
    string | null
  >(null);

  const syncEditableFields = useCallback((nextSkill: SkillEditableDetail) => {
    setName(nextSkill.name);
    setDescription(nextSkill.description);
    setInstructionsMarkdown(nextSkill.instructions_markdown);
  }, []);

  useEffect(() => {
    if (!skill || hydratedSkillId === skill.id) return;
    syncEditableFields(skill);
    setHydratedSkillId(skill.id);
  }, [hydratedSkillId, skill, syncEditableFields]);

  const isDirty = useMemo(() => {
    if (isCreating) {
      return Boolean(
        name || description || instructionsMarkdown || pendingFilesUpload
      );
    }
    if (!skill) return false;
    return (
      description !== skill.description ||
      instructionsMarkdown !== skill.instructions_markdown
    );
  }, [
    description,
    instructionsMarkdown,
    isCreating,
    name,
    pendingFilesUpload,
    skill,
  ]);

  const unsavedChanges = useUnsavedChangesGuard({
    isDirty,
    onDiscard: draftId ? () => discardSkillCreationDraft(draftId) : undefined,
  });

  const canManageSkill =
    isCreating ||
    skill?.user_permission === "OWNER" ||
    skill?.user_permission === "EDITOR";

  // A bundle upload rewrites name/description/instructions from SKILL.md, so
  // lock the detail fields while one is in flight: edits made mid-upload
  // would be clobbered by the post-upload sync (or race it via Save).
  const fieldsLocked =
    !canManageSkill || isPreparingFiles || isUploadingFiles || isSaving;

  const canSave =
    (isCreating || !!skill) &&
    canManageSkill &&
    !isPreparingFiles &&
    !isUploadingFiles &&
    isDirty &&
    !!name.trim() &&
    !!description.trim() &&
    !!instructionsMarkdown.trim() &&
    !isSaving;

  function leaveEditor() {
    router.push("/craft/v1/skills" as Route);
  }

  function handleCancel() {
    if (isSaving || isPreparingFiles || isUploadingFiles) return;
    unsavedChanges.requestLeave(leaveEditor);
  }

  async function refreshSkillList() {
    await mutate(SWR_KEYS.userSkills);
  }

  async function handleSave(
    event?: FormEvent<HTMLFormElement>,
    createDisabled = false
  ) {
    event?.preventDefault();
    if (!canSave) return;
    setIsSaving(true);
    try {
      if (isCreating) {
        const created = await createCustomSkillFromEditor(
          {
            name,
            description,
            instructions_markdown: instructionsMarkdown,
            auto_enable: !createDisabled,
          },
          pendingFilesUpload?.file
        );
        setConflictingSkillName(null);
        if (draftId) discardSkillCreationDraft(draftId);
        void refreshSkillList().catch((error: unknown) => {
          console.error("Failed to refresh skill list after creation", error);
        });
        toast.success(`Created "${created.name}"`);
        router.replace("/craft/v1/skills" as Route);
        return;
      }

      if (!skill) return;
      const updated = await patchUserSkill(skill.id, {
        description,
        instructions_markdown: instructionsMarkdown,
      });
      const nextSkill: SkillEditableDetail = {
        ...skill,
        ...updated,
        instructions_markdown: instructionsMarkdown.trim(),
      };
      await refreshSkill(nextSkill, { revalidate: false });
      syncEditableFields(nextSkill);
      await refreshSkillList();
      toast.success(`Saved "${updated.name}"`);
    } catch (err) {
      if (isCreating && !createDisabled && isSkillNameConflict(err)) {
        setConflictingSkillName(name.trim());
        return;
      }
      console.error("Failed to save skill", err);
      toast.error(err instanceof Error ? err.message : "Failed to save skill");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleSharingSaved() {
    await refreshSkill();
    await refreshSkillList();
  }

  async function applyFilesUpload(upload: PreparedSkillFilesUpload) {
    if (isCreating) {
      if (!upload.containsSkillMd) {
        setPendingFilesUpload(upload);
        return;
      }

      setIsUploadingFiles(true);
      try {
        const bundle = await inspectSkillBundle(upload.file);
        setName(bundle.name);
        setDescription(bundle.description);
        setInstructionsMarkdown(bundle.instructions_markdown);
        setPendingFilesUpload({
          ...upload,
          entries: bundle.files,
        });
      } catch (err) {
        console.error("Failed to inspect skill bundle", err);
        toast.error(
          err instanceof Error ? err.message : "Failed to inspect skill bundle"
        );
      } finally {
        setIsUploadingFiles(false);
      }
      return;
    }
    if (!skill || !canManageSkill || isDirty) return;

    setIsUploadingFiles(true);
    try {
      const updated = await uploadUserSkillFiles(skill.id, upload.file);
      await refreshSkill(updated, { revalidate: false });
      syncEditableFields(updated);
      await refreshSkillList();
      toast.success(`Updated files for "${updated.name}"`);
    } catch (err) {
      console.error("Failed to update skill files", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to update skill files"
      );
    } finally {
      setIsUploadingFiles(false);
    }
  }

  function handleFilesSelected(upload: PreparedSkillFilesUpload) {
    if (upload.containsSkillMd) {
      if (isCreating && !isDirty) {
        void applyFilesUpload(upload);
        return;
      }
      setFilesUploadToConfirm(upload);
      return;
    }
    void applyFilesUpload(upload);
  }

  function handleImportSelected(upload: PreparedSkillFilesUpload) {
    if (!upload.containsSkillMd) {
      toast.error("Import a SKILL.md, ZIP, or folder containing SKILL.md.");
      return;
    }
    handleFilesSelected(upload);
  }

  async function handleRemoveFile(path: string) {
    if (!skill || !canManageSkill || removingFilePath !== null) return;
    setRemovingFilePath(path);
    try {
      const updated = await removeUserSkillFile(skill.id, path);
      await refreshSkill(updated, { revalidate: false });
      await refreshSkillList();
      toast.success(`Removed "${path}"`);
    } catch (err) {
      console.error("Failed to remove skill file", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to remove skill file"
      );
    } finally {
      setRemovingFilePath(null);
    }
  }

  async function handleDeleteConfirmed() {
    if (!skill || !canManageSkill || isDeleting) return;

    setIsDeleting(true);
    try {
      await deleteUserSkill(skill.id);
      // The skill is gone — a transient list-refresh failure must not mask
      // the successful delete or block navigation off the dead editor page.
      void refreshSkillList();
      toast.success(`Deleted "${skill.name}"`);
      router.push("/craft/v1/skills" as Route);
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to delete skill"
      );
    } finally {
      setIsDeleting(false);
    }
  }

  const saveTooltip = isSaving
    ? isCreating
      ? "Saving skill..."
      : "Saving changes..."
    : !isCreating && !skill
      ? undefined
      : !canManageSkill
        ? "You don't have permission to edit this skill's details."
        : !name.trim()
          ? "Add a name before saving."
          : !description.trim()
            ? "Add a description before saving."
            : !instructionsMarkdown.trim()
              ? "Add instructions before saving."
              : !isDirty
                ? "No changes have been made."
                : undefined;

  const sharingStatus = skill ? getSharingStatus(skill) : null;
  const filesUploadDisabled =
    !canManageSkill ||
    isPreparingFiles ||
    isUploadingFiles ||
    isSaving ||
    (!isCreating && isDirty);
  const filesUploadTooltip =
    !isCreating && isDirty
      ? "Save detail changes before updating skill files."
      : isUploadingFiles
        ? "Updating skill files..."
        : !canManageSkill
          ? "You don't have permission to update this skill's files."
          : undefined;
  const displayedFiles = isCreating
    ? (pendingFilesUpload?.entries ?? [])
    : (skill?.files ?? []);

  return (
    <form
      className="h-full w-full"
      data-testid="SkillEditorPage/container"
      onSubmit={handleSave}
    >
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgBlocks}
          title={isCreating ? "Create skill" : "Edit skill"}
          description={
            isCreating
              ? "Build a personal skill"
              : "Update skill details and files"
          }
          rightChildren={
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                type="button"
                disabled={isSaving || isPreparingFiles || isUploadingFiles}
                onClick={handleCancel}
              >
                Cancel
              </Button>
              <Tooltip tooltip={saveTooltip} side="bottom">
                <Button disabled={!canSave} type="submit">
                  {isSaving ? "Saving..." : "Save"}
                </Button>
              </Tooltip>
            </div>
          }
          backButton={handleCancel}
          divider
        />

        <SettingsLayouts.Body>
          {!isCreating && isLoading && (
            <div className="flex min-h-40 items-center justify-center">
              <SvgSimpleLoader />
            </div>
          )}

          {!isCreating && error && !isLoading && (
            <MessageCard
              variant="error"
              title="Skill unavailable"
              description="This skill may not exist, may be built-in, or may not be editable by your account."
            />
          )}

          {(isCreating || skill) && !isLoading && !error && (
            <>
              {isCreating && !creationDraft && (
                <>
                  <Section gap={0.5} alignItems="stretch" height="auto">
                    <Card border="solid" rounding="lg" padding="sm">
                      <Section gap={0.5} alignItems="stretch" height="auto">
                        <Content
                          title="Have an existing skill?"
                          description="Import a SKILL.md, ZIP, or skill folder to prefill the form and include its files."
                          sizePreset="main-content"
                          variant="section"
                        />
                        <SkillFilesPicker
                          disabled={filesUploadDisabled}
                          busyLabel={
                            isUploadingFiles ? "Importing..." : undefined
                          }
                          buttonLabel="Import skill"
                          inputLabel="Import existing skill"
                          prompt="Choose a SKILL.md or ZIP, or drop a skill folder here."
                          onChange={handleImportSelected}
                          onError={(message) => toast.error(message)}
                          onPreparingChange={setIsPreparingFiles}
                        />
                      </Section>
                    </Card>
                  </Section>

                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />
                </>
              )}

              <Section alignItems="stretch">
                <Content
                  title="Details"
                  description="Define when and how Craft should use this skill."
                  sizePreset="main-content"
                  variant="section"
                />
                <InputVertical
                  withLabel="name"
                  title="Name"
                  disabled={fieldsLocked || !isCreating}
                  description={
                    isCreating
                      ? "Use lowercase letters, numbers, and single hyphens."
                      : "Skill names cannot be changed after creation."
                  }
                >
                  <Tooltip
                    tooltip={
                      isCreating
                        ? undefined
                        : "Skill names cannot be changed after creation."
                    }
                    side="top"
                  >
                    <div className="w-full">
                      <InputTypeIn
                        id="name"
                        name="name"
                        value={name}
                        onChange={(event) => setName(event.target.value)}
                        placeholder="Name your skill"
                        variant={
                          fieldsLocked || !isCreating ? "disabled" : "primary"
                        }
                      />
                    </div>
                  </Tooltip>
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title="Description"
                  description="Describe when this skill should be used."
                >
                  <InputTextArea
                    id="description"
                    name="description"
                    rows={2}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder="What does this skill help with?"
                    autoResize
                    maxRows={8}
                    variant={fieldsLocked ? "disabled" : "primary"}
                  />
                </InputVertical>
              </Section>

              <Divider paddingParallel="fit" paddingPerpendicular="fit" />

              <Section alignItems="stretch">
                <div className="flex w-full items-start justify-between gap-2">
                  <Content
                    title="Instructions"
                    description="Write the behavior and workflow this skill adds to Craft."
                    sizePreset="main-content"
                    variant="section"
                  />
                  <InstructionsDisplayModeToggle
                    value={instructionsDisplayMode}
                    onChange={setInstructionsDisplayMode}
                  />
                </div>

                <Card border="solid" rounding="lg" padding="sm">
                  {instructionsDisplayMode === "raw" ? (
                    <InputTextArea
                      id="instructions_markdown"
                      name="instructions_markdown"
                      rows={10}
                      value={instructionsMarkdown}
                      onChange={(event) =>
                        setInstructionsMarkdown(event.target.value)
                      }
                      placeholder="Write the skill instructions."
                      variant={fieldsLocked ? "disabled" : "internal"}
                    />
                  ) : (
                    <div className="min-h-[34rem] max-h-[70dvh] overflow-y-auto overflow-x-hidden rounded-08 bg-background-neutral-00 p-2">
                      <CompactMarkdown>
                        {instructionsMarkdown || "No instructions yet."}
                      </CompactMarkdown>
                    </div>
                  )}
                </Card>
              </Section>

              <Divider paddingParallel="fit" paddingPerpendicular="fit" />

              <Section gap={0.5} alignItems="stretch" height="auto">
                <Content
                  title="Supporting files"
                  description="Add references, scripts, assets, or other files used by this skill. ZIP files are unpacked automatically."
                  sizePreset="main-content"
                  variant="section"
                />
                <Card border="solid" rounding="lg">
                  <SkillFileTree
                    files={displayedFiles}
                    onRemove={
                      skill && canManageSkill ? handleRemoveFile : undefined
                    }
                    removingPath={removingFilePath}
                    removeDisabled={filesUploadDisabled}
                    emptyMessage={
                      pendingFilesUpload?.entries === null
                        ? "Files from this upload will appear after you create the skill."
                        : undefined
                    }
                  />
                  {canManageSkill && (
                    <div className="border-t border-border-01 p-2">
                      <Tooltip tooltip={filesUploadTooltip} side="bottom">
                        <div>
                          <SkillFilesPicker
                            value={pendingFilesUpload}
                            disabled={filesUploadDisabled}
                            inputLabel="Add supporting files"
                            busyLabel={
                              isUploadingFiles ? "Uploading..." : undefined
                            }
                            onChange={handleFilesSelected}
                            onError={(message) => toast.error(message)}
                            onPreparingChange={setIsPreparingFiles}
                          />
                        </div>
                      </Tooltip>
                    </div>
                  )}
                </Card>
              </Section>

              {skill && (
                <>
                  <Divider paddingParallel="fit" paddingPerpendicular="fit" />

                  <Section gap={0.5} alignItems="stretch" height="auto">
                    <Content
                      title="Management"
                      description="Control who can use this skill."
                      sizePreset="main-content"
                      variant="section"
                    />
                    <Card border="solid" rounding="lg">
                      <Section>
                        {sharingStatus && (
                          <InputHorizontal
                            title="Sharing"
                            description={sharingStatus.description}
                            center
                          >
                            <div className="flex items-center gap-2">
                              <Tag
                                title={sharingStatus.title}
                                color={sharingStatus.color}
                              />
                              {canManageSkill && (
                                <Button
                                  type="button"
                                  prominence="secondary"
                                  icon={SvgShare}
                                  onClick={() => setShareOpen(true)}
                                >
                                  Edit sharing
                                </Button>
                              )}
                            </div>
                          </InputHorizontal>
                        )}
                      </Section>
                    </Card>
                  </Section>

                  {canManageSkill && (
                    <>
                      <Divider
                        paddingParallel="fit"
                        paddingPerpendicular="fit"
                      />

                      <Card border="solid" rounding="lg">
                        <Section>
                          <InputHorizontal
                            title="Delete this skill"
                            description="Anyone using this skill will lose access. Deletion cannot be undone."
                            center
                          >
                            <Button
                              type="button"
                              variant="danger"
                              prominence="secondary"
                              icon={SvgTrash}
                              disabled={isDeleting}
                              onClick={() => setDeleteOpen(true)}
                            >
                              Delete skill
                            </Button>
                          </InputHorizontal>
                        </Section>
                      </Card>
                    </>
                  )}
                </>
              )}
            </>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <ShareSkillModal
        skill={shareOpen ? (skill ?? null) : null}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
        onSaved={handleSharingSaved}
      />

      {filesUploadToConfirm && (
        <ConfirmationModalLayout
          icon={SvgAlertTriangle}
          title={isCreating ? "Import this skill?" : "Replace skill content?"}
          onClose={() => setFilesUploadToConfirm(null)}
          submit={
            <Button
              type="button"
              onClick={() => {
                const upload = filesUploadToConfirm;
                setFilesUploadToConfirm(null);
                void applyFilesUpload(upload);
              }}
            >
              {isCreating ? "Import skill" : "Replace content"}
            </Button>
          }
        >
          {isCreating
            ? "This upload includes SKILL.md. Continuing will replace the current name, description, instructions, and files with the uploaded bundle."
            : "This upload must use the same skill name. Continuing will replace the description, instructions, and files with the uploaded bundle."}
        </ConfirmationModalLayout>
      )}

      {conflictingSkillName && (
        <SkillNameConflictModal
          skillName={conflictingSkillName}
          onClose={() => setConflictingSkillName(null)}
          onConfirm={() => void handleSave(undefined, true)}
          pending={isSaving}
        />
      )}

      <UnsavedChangesModal
        open={unsavedChanges.confirmationOpen}
        onCancel={unsavedChanges.cancelLeave}
        onDiscard={unsavedChanges.discardAndLeave}
      />

      {skill && deleteOpen && (
        <ConfirmEntityModal
          danger
          entityType="skill"
          entityName={skill.name}
          actionButtonText={isDeleting ? "Deleting..." : "Delete"}
          onClose={() => setDeleteOpen(false)}
          onSubmit={handleDeleteConfirmed}
        />
      )}
    </form>
  );
}
