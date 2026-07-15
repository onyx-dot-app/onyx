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
  InputTypeIn,
  MessageCard,
  Switch,
  Tag,
  Tooltip,
} from "@opal/components";
import {
  SvgArrowLeft,
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
} from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import InputTextArea from "@/refresh-components/inputs/InputTextArea";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  createCustomSkillFromEditor,
  deleteUserSkill,
  patchUserSkill,
  removeUserSkillFile,
  uploadUserSkillFiles,
} from "@/lib/skills/api";
import type { CustomSkill, SkillEditableDetail } from "@/lib/skills/types";
import type { PreparedSkillFilesUpload } from "@/lib/skills/bundleUpload";
import { toast } from "@/hooks/useToast";
import InstructionsDisplayModeToggle, {
  type InstructionsDisplayMode,
} from "@/sections/skills/InstructionsDisplayModeToggle";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import SkillFileTree from "@/sections/skills/SkillFileTree";
import SkillFilesPicker from "@/sections/skills/SkillFilesPicker";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";

interface SkillEditorPageProps {
  skillId?: string;
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

export default function SkillEditorPage({ skillId }: SkillEditorPageProps) {
  const isCreating = skillId === undefined;
  const router = useRouter();
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

  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructionsMarkdown, setInstructionsMarkdown] = useState("");
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("raw");
  const [hydratedSkillId, setHydratedSkillId] = useState<string | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isPreparingFiles, setIsPreparingFiles] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [pendingFilesUpload, setPendingFilesUpload] =
    useState<PreparedSkillFilesUpload | null>(null);
  const [filesUploadToConfirm, setFilesUploadToConfirm] =
    useState<PreparedSkillFilesUpload | null>(null);
  const [removingFilePath, setRemovingFilePath] = useState<string | null>(null);
  const [isTogglingEnabled, setIsTogglingEnabled] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

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
        slug ||
        name ||
        description ||
        instructionsMarkdown ||
        pendingFilesUpload
      );
    }
    if (!skill) return false;
    return (
      name !== skill.name ||
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
    slug,
  ]);

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
    (!isCreating || !!slug.trim()) &&
    !!name.trim() &&
    !!description.trim() &&
    !!instructionsMarkdown.trim() &&
    !isSaving;

  function navigateBack() {
    router.push("/craft/v1/skills" as Route);
  }

  async function refreshSkillList() {
    await mutate(SWR_KEYS.userSkills);
  }

  async function updateLocalSkill(updated: CustomSkill) {
    if (!skill) return;
    const nextSkill: SkillEditableDetail = { ...skill, ...updated };
    await refreshSkill(nextSkill, { revalidate: false });
    await refreshSkillList();
  }

  async function handleSave(event?: FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!canSave) return;
    setIsSaving(true);
    try {
      if (isCreating) {
        const created = await createCustomSkillFromEditor(
          {
            slug,
            name,
            description,
            instructions_markdown: instructionsMarkdown,
          },
          pendingFilesUpload?.file
        );
        await refreshSkillList();
        toast.success(`Created "${created.name}"`);
        router.replace(`/craft/v1/skills/edit/${created.id}` as Route);
        return;
      }

      if (!skill) return;
      const updated = await patchUserSkill(skill.id, {
        name,
        description,
        instructions_markdown: instructionsMarkdown,
      });
      const refreshed = await refreshSkill();
      if (refreshed) {
        syncEditableFields(refreshed);
      } else {
        const nextSkill: SkillEditableDetail = {
          ...skill,
          ...updated,
          instructions_markdown: instructionsMarkdown.trim(),
        };
        await refreshSkill(nextSkill, { revalidate: false });
        syncEditableFields(nextSkill);
      }
      await refreshSkillList();
      toast.success(`Saved "${updated.name}"`);
    } catch (err) {
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
      setPendingFilesUpload(upload);
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
      setFilesUploadToConfirm(upload);
      return;
    }
    void applyFilesUpload(upload);
  }

  async function handleRemoveFile(path: string) {
    if (!skill || !canManageSkill || removingFilePath !== null) return;
    setRemovingFilePath(path);
    try {
      const updated = await removeUserSkillFile(skill.id, path);
      await refreshSkill(updated, { revalidate: false });
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

  async function handleToggleEnabled(enabled: boolean) {
    if (!skill || !canManageSkill) return;

    setIsTogglingEnabled(true);
    try {
      const updated = await patchUserSkill(skill.id, { enabled });
      await updateLocalSkill(updated);
      toast.success(`${enabled ? "Enabled" : "Disabled"} "${updated.name}"`);
    } catch (err) {
      console.error("Failed to toggle skill", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to update skill"
      );
    } finally {
      setIsTogglingEnabled(false);
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
      ? "Creating skill..."
      : "Saving changes..."
    : !isCreating && !skill
      ? undefined
      : !canManageSkill
        ? "You don't have permission to edit this skill's details."
        : isCreating && !slug.trim()
          ? "Add a slug before creating the skill."
          : !name.trim()
            ? "Add a title before saving."
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
          description={isCreating ? "Build a personal skill" : skill?.slug}
          rightChildren={
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                type="button"
                icon={SvgArrowLeft}
                onClick={navigateBack}
              >
                Cancel
              </Button>
              <Tooltip tooltip={saveTooltip} side="bottom">
                <Button disabled={!canSave} type="submit">
                  {isSaving
                    ? isCreating
                      ? "Creating..."
                      : "Saving..."
                    : isCreating
                      ? "Create"
                      : "Save"}
                </Button>
              </Tooltip>
            </div>
          }
          backButton
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
              <Section alignItems="stretch">
                {isCreating && (
                  <InputVertical
                    withLabel="slug"
                    title="Slug"
                    description="A lowercase identifier used when Craft loads this skill. Use letters, numbers, and hyphens."
                  >
                    <InputTypeIn
                      id="slug"
                      name="slug"
                      value={slug}
                      onChange={(event) => setSlug(event.target.value)}
                      placeholder="customer-research"
                      variant={fieldsLocked ? "disabled" : "primary"}
                    />
                  </InputVertical>
                )}
                <InputVertical withLabel="name" title="Name">
                  <InputTypeIn
                    id="name"
                    name="name"
                    value={name}
                    onChange={(event) => setName(event.target.value)}
                    placeholder="Name your skill"
                    variant={fieldsLocked ? "disabled" : "primary"}
                  />
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title="Description"
                  description="Describe when this skill should be used."
                >
                  <InputTextArea
                    id="description"
                    name="description"
                    rows={4}
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
                      rows={22}
                      value={instructionsMarkdown}
                      onChange={(event) =>
                        setInstructionsMarkdown(event.target.value)
                      }
                      className="border-0"
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
                  title="Files"
                  description="Add scripts, references, and other files this skill needs. ZIP files are unpacked. A bundle containing SKILL.md replaces the current bundle and editor content."
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
                      description="Control who can use this skill and whether Craft can currently select it."
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

                        {canManageSkill && (
                          <InputHorizontal
                            title={skill.enabled ? "Enabled" : "Disabled"}
                            description={
                              skill.enabled
                                ? "Craft can use this skill when it is relevant."
                                : "Craft will not use this skill until it is re-enabled."
                            }
                            center
                          >
                            <Switch
                              checked={skill.enabled}
                              disabled={isTogglingEnabled}
                              onCheckedChange={handleToggleEnabled}
                            />
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
          title="Replace skill content?"
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
              Continue
            </Button>
          }
        >
          This upload includes SKILL.md. Continuing will replace the current
          title, description, instructions, and files with the uploaded bundle.
        </ConfirmationModalLayout>
      )}

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
