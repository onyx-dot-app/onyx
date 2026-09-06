"use client";

import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type FormEvent,
} from "react";
import { useTranslations } from "next-intl";
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
import { useUser } from "@/providers/UserProvider";
import { externalAppAdminUrl } from "@/app/craft/v1/apps/admin/skillAssociationNavigation";

interface SkillEditorPageProps {
  skillId?: string;
  draftId?: string;
  externalAppId?: number;
  externalAppName?: string;
}

type SkillsTranslate = ReturnType<typeof useTranslations<"skills">>;

function getSharingStatus(
  skill: SkillEditableDetail,
  t: SkillsTranslate
): {
  title: string;
  description: string;
  color: "blue" | "gray" | "purple";
} {
  if (skill.external_app) {
    return {
      title: t("editor.sharing.organization.title"),
      description: t("modals.share.externalAppNotice", {
        appName: skill.external_app.name,
      }),
      color: "blue",
    };
  }
  if (skill.public_permission !== null) {
    return {
      title: t("editor.sharing.organization.title"),
      description:
        skill.public_permission === "EDITOR"
          ? t("editor.sharing.organization.editorDescription")
          : t("editor.sharing.organization.viewerDescription"),
      color: "blue",
    };
  }

  const userCount = skill.user_shares.length;
  const groupCount = skill.group_shares.length;
  const shareCount = userCount + groupCount;
  if (shareCount > 0) {
    return {
      title: t("editor.sharing.shares.title", { count: shareCount }),
      description: t("editor.sharing.shares.description"),
      color: "gray",
    };
  }

  return {
    title: t("editor.sharing.personal.title"),
    description: t("editor.sharing.personal.description"),
    color: "purple",
  };
}

export default function SkillEditorPage({
  skillId,
  draftId,
  externalAppId,
  externalAppName,
}: SkillEditorPageProps) {
  const t = useTranslations("skills");
  const isCreating = skillId === undefined;
  const hasAppContext = externalAppId !== undefined;
  const isCreatingForApp = isCreating && hasAppContext;
  const router = useRouter();
  const { isAdmin } = useUser();
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
  const [appConflictingSkillName, setAppConflictingSkillName] = useState<
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
    router.push(
      hasAppContext
        ? externalAppAdminUrl(externalAppId)
        : ("/craft/v1/skills" as Route)
    );
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
    setAppConflictingSkillName(null);
    try {
      if (isCreating) {
        const created = await createCustomSkillFromEditor(
          {
            name,
            description,
            instructions_markdown: instructionsMarkdown,
            auto_enable: isCreatingForApp ? false : !createDisabled,
            ...(externalAppId !== undefined
              ? { external_app_id: externalAppId }
              : {}),
          },
          pendingFilesUpload?.file
        );
        setConflictingSkillName(null);
        if (draftId) discardSkillCreationDraft(draftId);
        if (isCreatingForApp) {
          // The app editor reads this cache as soon as we return. Wait for its
          // association to refresh so the newly created skill is visible.
          try {
            await mutate(SWR_KEYS.buildExternalAppsAdmin);
          } catch (error) {
            console.error(
              "Failed to refresh external app after skill creation",
              error
            );
          }
        }
        void mutate(SWR_KEYS.userSkills).catch((error: unknown) => {
          console.error("Failed to refresh skill data after creation", error);
        });
        toast.success(t("editor.toasts.created", { name: created.name }));
        router.replace(
          isCreatingForApp
            ? externalAppAdminUrl(externalAppId)
            : ("/craft/v1/skills" as Route)
        );
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
      toast.success(t("editor.toasts.saved", { name: updated.name }));
    } catch (err) {
      if (isCreatingForApp && isSkillNameConflict(err)) {
        setAppConflictingSkillName(name.trim());
        return;
      }
      if (
        isCreating &&
        !isCreatingForApp &&
        !createDisabled &&
        isSkillNameConflict(err)
      ) {
        setConflictingSkillName(name.trim());
        return;
      }
      console.error("Failed to save skill", err);
      toast.error(
        err instanceof Error ? err.message : t("editor.toasts.saveFailed")
      );
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
          err instanceof Error ? err.message : t("editor.toasts.inspectFailed")
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
      toast.success(t("editor.toasts.filesUpdated", { name: updated.name }));
    } catch (err) {
      console.error("Failed to update skill files", err);
      toast.error(
        err instanceof Error
          ? err.message
          : t("editor.toasts.filesUpdateFailed")
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
      toast.error(t("editor.toasts.importMissingSkillMd"));
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
      toast.success(t("editor.toasts.fileRemoved", { path }));
    } catch (err) {
      console.error("Failed to remove skill file", err);
      toast.error(
        err instanceof Error ? err.message : t("editor.toasts.fileRemoveFailed")
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
      if (hasAppContext) {
        try {
          await mutate(SWR_KEYS.buildExternalAppsAdmin);
        } catch (error) {
          console.error(
            "Failed to refresh external app after skill deletion",
            error
          );
        }
      }
      // The skill is gone — a transient list-refresh failure must not mask
      // the successful delete or block navigation off the dead editor page.
      void refreshSkillList();
      toast.success(t("editor.toasts.deleted", { name: skill.name }));
      leaveEditor();
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(
        err instanceof Error ? err.message : t("editor.toasts.deleteFailed")
      );
    } finally {
      setIsDeleting(false);
    }
  }

  const saveTooltip = isSaving
    ? isCreating
      ? t("editor.saveTooltip.savingSkill")
      : t("editor.saveTooltip.savingChanges")
    : !isCreating && !skill
      ? undefined
      : !canManageSkill
        ? t("editor.saveTooltip.noPermission")
        : !name.trim()
          ? t("editor.saveTooltip.missingName")
          : !description.trim()
            ? t("editor.saveTooltip.missingDescription")
            : !instructionsMarkdown.trim()
              ? t("editor.saveTooltip.missingInstructions")
              : !isDirty
                ? t("editor.saveTooltip.noChanges")
                : undefined;

  const sharingStatus = skill ? getSharingStatus(skill, t) : null;
  const filesUploadDisabled =
    !canManageSkill ||
    isPreparingFiles ||
    isUploadingFiles ||
    isSaving ||
    (!isCreating && isDirty);
  const filesUploadTooltip =
    !isCreating && isDirty
      ? t("editor.filesTooltip.saveFirst")
      : isUploadingFiles
        ? t("editor.filesTooltip.updating")
        : !canManageSkill
          ? t("editor.filesTooltip.noPermission")
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
          title={
            isCreating
              ? t("editor.header.createTitle")
              : t("editor.header.editTitle")
          }
          description={
            isCreating
              ? isCreatingForApp
                ? t("editor.header.createForAppDescription", {
                    appName:
                      externalAppName ?? t("editor.header.appFallbackName"),
                  })
                : t("editor.header.createDescription")
              : t("editor.header.editDescription")
          }
          rightChildren={
            <div className="flex items-center gap-2">
              <Button
                prominence="secondary"
                type="button"
                disabled={isSaving || isPreparingFiles || isUploadingFiles}
                onClick={handleCancel}
              >
                {t("editor.header.cancel.label")}
              </Button>
              <Tooltip tooltip={saveTooltip} side="bottom">
                <Button disabled={!canSave} type="submit">
                  {isSaving
                    ? t("editor.header.save.pendingLabel")
                    : t("editor.header.save.label")}
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
              title={t("editor.loadError.title")}
              description={t("editor.loadError.description")}
            />
          )}

          {(isCreating || skill) && !isLoading && !error && (
            <>
              {appConflictingSkillName && (
                <MessageCard
                  variant="error"
                  title={t("editor.appConflict.title")}
                  description={t("editor.appConflict.description", {
                    appName:
                      externalAppName ?? t("editor.header.appFallbackName"),
                    skillName: appConflictingSkillName,
                  })}
                />
              )}

              {isCreating && !creationDraft && (
                <>
                  <Section gap={2} alignItems="stretch" height="auto">
                    <Card border="solid" rounding={4} padding={2}>
                      <Section gap={2} alignItems="stretch" height="auto">
                        <Content
                          title={t("editor.import.title")}
                          description={t("editor.import.description")}
                          sizePreset="main-content"
                          variant="section"
                        />
                        <SkillFilesPicker
                          disabled={filesUploadDisabled}
                          busyLabel={
                            isUploadingFiles
                              ? t("editor.import.busyLabel")
                              : undefined
                          }
                          buttonLabel={t("editor.import.button.label")}
                          inputLabel={t("editor.import.input.ariaLabel")}
                          prompt={t("editor.import.prompt")}
                          onChange={handleImportSelected}
                          onError={(message) => toast.error(message)}
                          onPreparingChange={setIsPreparingFiles}
                        />
                      </Section>
                    </Card>
                  </Section>

                  <Divider paddingParallel={0} paddingPerpendicular={0} />
                </>
              )}

              <Section alignItems="stretch">
                <Content
                  title={t("editor.details.title")}
                  description={t("editor.details.description")}
                  sizePreset="main-content"
                  variant="section"
                />
                <InputVertical
                  withLabel="name"
                  title={t("editor.details.name.title")}
                  disabled={fieldsLocked || !isCreating}
                  description={
                    isCreating
                      ? t("editor.details.name.createDescription")
                      : t("editor.details.name.lockedDescription")
                  }
                >
                  <Tooltip
                    tooltip={
                      isCreating
                        ? undefined
                        : t("editor.details.name.lockedDescription")
                    }
                    side="top"
                  >
                    <div className="w-full">
                      <InputTypeIn
                        id="name"
                        name="name"
                        value={name}
                        onChange={(event) => {
                          setName(event.target.value);
                          setAppConflictingSkillName(null);
                        }}
                        placeholder={t("editor.details.name.placeholder")}
                        variant={
                          fieldsLocked || !isCreating ? "disabled" : "primary"
                        }
                      />
                    </div>
                  </Tooltip>
                </InputVertical>

                <InputVertical
                  withLabel="description"
                  title={t("editor.details.descriptionField.title")}
                  description={t("editor.details.descriptionField.description")}
                >
                  <InputTextArea
                    id="description"
                    name="description"
                    rows={2}
                    value={description}
                    onChange={(event) => setDescription(event.target.value)}
                    placeholder={t(
                      "editor.details.descriptionField.placeholder"
                    )}
                    autoResize
                    maxRows={8}
                    variant={fieldsLocked ? "disabled" : "primary"}
                  />
                </InputVertical>
              </Section>

              <Divider paddingParallel={0} paddingPerpendicular={0} />

              <Section alignItems="stretch">
                <div className="flex w-full items-start justify-between gap-2">
                  <Content
                    title={t("editor.instructions.title")}
                    description={t("editor.instructions.description")}
                    sizePreset="main-content"
                    variant="section"
                  />
                  <InstructionsDisplayModeToggle
                    value={instructionsDisplayMode}
                    onChange={setInstructionsDisplayMode}
                  />
                </div>

                <Card border="solid" rounding={4} padding={2}>
                  {instructionsDisplayMode === "raw" ? (
                    <InputTextArea
                      id="instructions_markdown"
                      name="instructions_markdown"
                      rows={10}
                      value={instructionsMarkdown}
                      onChange={(event) =>
                        setInstructionsMarkdown(event.target.value)
                      }
                      placeholder={t("editor.instructions.placeholder")}
                      variant={fieldsLocked ? "disabled" : "internal"}
                    />
                  ) : (
                    <div className="min-h-[34rem] max-h-[70dvh] overflow-y-auto overflow-x-hidden rounded-08 bg-background-neutral-00 p-2">
                      <CompactMarkdown>
                        {instructionsMarkdown ||
                          t("editor.instructions.emptyFallback")}
                      </CompactMarkdown>
                    </div>
                  )}
                </Card>
              </Section>

              <Divider paddingParallel={0} paddingPerpendicular={0} />

              <Section gap={2} alignItems="stretch" height="auto">
                <Content
                  title={t("editor.files.title")}
                  description={t("editor.files.description")}
                  sizePreset="main-content"
                  variant="section"
                />
                <Card border="solid" rounding={4}>
                  <SkillFileTree
                    files={displayedFiles}
                    onRemove={
                      skill && canManageSkill ? handleRemoveFile : undefined
                    }
                    removingPath={removingFilePath}
                    removeDisabled={filesUploadDisabled}
                    emptyMessage={
                      pendingFilesUpload?.entries === null
                        ? t("editor.files.pendingUpload.emptyMessage")
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
                            inputLabel={t("editor.files.input.ariaLabel")}
                            busyLabel={
                              isUploadingFiles
                                ? t("editor.files.busyLabel")
                                : undefined
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
                  <Divider paddingParallel={0} paddingPerpendicular={0} />

                  <Section gap={2} alignItems="stretch" height="auto">
                    <Content
                      title={t("editor.management.title")}
                      description={t("editor.management.description")}
                      sizePreset="main-content"
                      variant="section"
                    />
                    <Card border="solid" rounding={4}>
                      <Section>
                        {skill.external_app && (
                          <InputHorizontal
                            title={t("editor.management.externalApp.title")}
                            description={
                              skill.external_app.ready
                                ? t(
                                    "editor.management.externalApp.readyDescription",
                                    { appName: skill.external_app.name }
                                  )
                                : skill.external_app.enabled
                                  ? t(
                                      "modals.preview.unavailable.appNotConnected",
                                      { appName: skill.external_app.name }
                                    )
                                  : t(
                                      "modals.preview.unavailable.appDisabled",
                                      {
                                        appName: skill.external_app.name,
                                      }
                                    )
                            }
                            center
                          >
                            <div className="flex items-center gap-2">
                              <Tag
                                title={skill.external_app.name}
                                color={
                                  skill.external_app.ready ? "blue" : "amber"
                                }
                              />
                              {isAdmin && (
                                <Button
                                  type="button"
                                  prominence="secondary"
                                  href={externalAppAdminUrl(
                                    skill.external_app.external_app_id
                                  )}
                                >
                                  {t(
                                    "editor.management.externalApp.manage.label"
                                  )}
                                </Button>
                              )}
                            </div>
                          </InputHorizontal>
                        )}
                        {sharingStatus && (
                          <InputHorizontal
                            title={t("editor.management.sharing.title")}
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
                                  {t("editor.management.sharing.edit.label")}
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
                      <Divider paddingParallel={0} paddingPerpendicular={0} />

                      <Card border="solid" rounding={4}>
                        <Section>
                          <InputHorizontal
                            title={t("editor.delete.title")}
                            description={t("editor.delete.description")}
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
                              {t("editor.delete.button.label")}
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
          title={
            isCreating
              ? t("editor.confirmUpload.importTitle")
              : t("editor.confirmUpload.replaceTitle")
          }
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
              {isCreating
                ? t("editor.confirmUpload.importSubmit.label")
                : t("editor.confirmUpload.replaceSubmit.label")}
            </Button>
          }
        >
          {isCreating
            ? t("editor.confirmUpload.importBody")
            : t("editor.confirmUpload.replaceBody")}
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
          entityType={t("editor.deleteModal.entityType")}
          entityName={skill.name}
          actionButtonText={
            isDeleting
              ? t("editor.deleteModal.pendingLabel")
              : t("editor.deleteModal.label")
          }
          onClose={() => setDeleteOpen(false)}
          onSubmit={handleDeleteConfirmed}
        />
      )}
    </form>
  );
}
