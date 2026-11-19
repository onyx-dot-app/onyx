"use client";

import { useNavigation } from "@opal/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Card,
  CompactMarkdown,
  Divider,
  InputTextArea,
  InputTypeIn,
  Tooltip,
  useCreateModal,
} from "@opal/components";
import { SvgAlertTriangle, SvgBlocks } from "@opal/icons";
import {
  Content,
  InputVertical,
  SettingsLayouts,
  Section,
  toast,
} from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { refreshSkillListsChecked } from "@/lib/skills/cache";
import {
  createCustomSkillFromEditor,
  inspectSkillBundle,
  isSkillNameConflict,
} from "@/lib/skills/api";
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
import SkillSharingSummary from "@/sections/skills/SkillSharingSummary";
import {
  emptySkillSharingDraft,
  serializeSkillSharing,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import SkillNameConflictModal from "@/sections/modals/skills/SkillNameConflictModal";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import SkillFileTree from "@/sections/skills/SkillFileTree";
import SkillFilesPicker from "@/sections/skills/SkillFilesPicker";
import { ConfirmationModalLayout } from "@opal/layouts";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useSkillLimitCopy } from "@/lib/skills/hooks";
import { customizeTabHref, skillHref } from "@/lib/customize/paths";

interface SkillEditorPageProps {
  draftId?: string;
}

/** Creates a skill. An existing skill is edited in place on its Contents tab. */
export default function SkillEditorPage({ draftId }: SkillEditorPageProps) {
  const t = useTranslations("skills");
  const { describeError } = useSkillLimitCopy();
  const navigation = useNavigation();
  const { user } = useUser();
  const { isGlobalHolder: canManageOrgSkills } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
  const creationDraft = useMemo(
    () => (draftId ? getSkillCreationDraft(draftId) : undefined),
    [draftId]
  );
  const { mutate, cache } = useSWRConfig();

  const [name, setName] = useState(creationDraft?.contents.name ?? "");
  const [description, setDescription] = useState(
    creationDraft?.contents.description ?? ""
  );
  const [instructionsMarkdown, setInstructionsMarkdown] = useState(
    creationDraft?.contents.instructions_markdown ?? ""
  );
  const [instructionsDisplayMode, setInstructionsDisplayMode] =
    useState<InstructionsDisplayMode>("raw");
  const [creationSharing, setCreationSharing] =
    useState<SkillSharingDraft | null>(null);
  const sharingDraft: SkillSharingDraft = {
    ...emptySkillSharingDraft(
      name || t("editor.header.createTitle"),
      user ? { id: user.id, email: user.email } : null
    ),
    ...creationSharing,
    name: name || t("editor.header.createTitle"),
  };
  const [shareOpen, setShareOpen] = useState(false);
  const confirmUploadModal = useCreateModal();
  const nameConflictModal = useCreateModal();
  const [isSaving, setIsSaving] = useState(false);
  const [isPreparingFiles, setIsPreparingFiles] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [pendingFilesUpload, setPendingFilesUpload] =
    useState<PreparedSkillFilesUpload | null>(creationDraft?.upload ?? null);
  const [filesUploadToConfirm, setFilesUploadToConfirm] =
    useState<PreparedSkillFilesUpload | null>(null);
  const [conflictingSkillName, setConflictingSkillName] = useState<
    string | null
  >(null);

  const isDirty = Boolean(
    name ||
    description ||
    instructionsMarkdown ||
    pendingFilesUpload ||
    creationSharing
  );

  const unsavedChanges = useUnsavedChangesGuard({
    isDirty,
    onDiscard: draftId ? () => discardSkillCreationDraft(draftId) : undefined,
  });

  // A bundle upload rewrites name/description/instructions from SKILL.md, so
  // lock the fields while one is in flight.
  const fieldsLocked = isPreparingFiles || isUploadingFiles || isSaving;

  const canSave =
    !isPreparingFiles &&
    !isUploadingFiles &&
    isDirty &&
    !!name.trim() &&
    !!description.trim() &&
    !!instructionsMarkdown.trim() &&
    !isSaving;

  function handleCancel() {
    if (isSaving || isPreparingFiles || isUploadingFiles) return;
    unsavedChanges.requestLeave(() =>
      navigation.go(customizeTabHref("skills"))
    );
  }

  async function handleSave(
    event?: FormEvent<HTMLFormElement>,
    createDisabled = false
  ) {
    event?.preventDefault();
    if (!canSave) return;
    setIsSaving(true);
    try {
      const created = await createCustomSkillFromEditor(
        {
          name,
          description,
          instructions_markdown: instructionsMarkdown,
          auto_enable: !createDisabled,
          sharing: creationSharing
            ? serializeSkillSharing(creationSharing, canManageOrgSkills)
            : undefined,
        },
        pendingFilesUpload?.file
      );
      nameConflictModal.toggle(false);
      if (draftId) discardSkillCreationDraft(draftId);
      // The skill page finds the new skill in the user's list; the other
      // lists refresh in the background.
      await mutate(SWR_KEYS.userSkills).catch(() => undefined);
      void refreshSkillListsChecked(mutate, cache).then((ok) => {
        if (!ok) toast.error(t("page.toasts.listRefreshFailed"));
      });
      toast.success(t("editor.toasts.created", { name: created.name }));
      navigation.go(skillHref(created.id), { replace: true });
    } catch (err) {
      if (!createDisabled && isSkillNameConflict(err)) {
        setConflictingSkillName(name.trim());
        nameConflictModal.toggle(true);
        return;
      }
      console.error("Failed to save skill", err);
      toast.error(describeError(err, t("editor.toasts.saveFailed")));
    } finally {
      setIsSaving(false);
    }
  }

  async function applyFilesUpload(upload: PreparedSkillFilesUpload) {
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
      setPendingFilesUpload({ ...upload, entries: bundle.files });
    } catch (err) {
      console.error("Failed to inspect skill bundle", err);
      toast.error(
        err instanceof Error ? err.message : t("editor.toasts.inspectFailed")
      );
    } finally {
      setIsUploadingFiles(false);
    }
  }

  function handleFilesSelected(upload: PreparedSkillFilesUpload) {
    if (upload.containsSkillMd && isDirty) {
      setFilesUploadToConfirm(upload);
      confirmUploadModal.toggle(true);
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

  const saveTooltip = isSaving
    ? t("editor.saveTooltip.savingSkill")
    : !name.trim()
      ? t("editor.saveTooltip.missingName")
      : !description.trim()
        ? t("editor.saveTooltip.missingDescription")
        : !instructionsMarkdown.trim()
          ? t("editor.saveTooltip.missingInstructions")
          : undefined;

  const filesUploadDisabled = fieldsLocked;
  const filesUploadTooltip = isUploadingFiles
    ? t("editor.filesTooltip.updating")
    : undefined;
  const displayedFiles = pendingFilesUpload?.entries ?? [];

  return (
    <form
      className="h-full w-full"
      data-testid="SkillEditorPage/container"
      onSubmit={handleSave}
    >
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgBlocks}
          title={t("editor.header.createTitle")}
          description={t("editor.header.createDescription")}
          cancel={handleCancel}
          actions={[
            <Tooltip key="save" tooltip={saveTooltip} side="bottom">
              <Button disabled={!canSave} type="submit">
                {isSaving
                  ? t("editor.header.save.pendingLabel")
                  : t("editor.header.save.label")}
              </Button>
            </Tooltip>,
          ]}
          divider
        />

        <SettingsLayouts.Body>
          <>
            {!creationDraft && (
              <>
                <Section gap={2} alignItems="stretch" height="auto">
                  <Card border="solid" rounding={4} padding={2}>
                    <Section gap={2} alignItems="stretch" height="auto">
                      <Content
                        font="main-content-emphasis"
                        title={t("editor.import.title")}
                        description={t("editor.import.description")}
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

            <SkillSharingSummary
              title={t("editor.creationAccess.title")}
              draft={sharingDraft}
              count={1}
              configureLabel={t("editor.management.sharing.edit.label")}
              disabled={fieldsLocked}
              onConfigure={() => setShareOpen(true)}
            />

            <Section alignItems="stretch">
              <Content
                font="main-content-emphasis"
                title={t("editor.details.title")}
                description={t("editor.details.description")}
              />
              <InputVertical
                withLabel="name"
                title={t("editor.details.name.title")}
                disabled={fieldsLocked}
                description={t("editor.details.name.createDescription")}
              >
                <InputTypeIn
                  id="name"
                  name="name"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder={t("editor.details.name.placeholder")}
                  variant={fieldsLocked ? "disabled" : "primary"}
                />
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
                  placeholder={t("editor.details.descriptionField.placeholder")}
                  autoResize
                  maxRows={8}
                  variant={fieldsLocked ? "disabled" : "primary"}
                />
              </InputVertical>
            </Section>

            <Divider paddingParallel={0} paddingPerpendicular={0} />

            <Section alignItems="stretch">
              <Section
                height="auto"
                flexDirection="row"
                alignItems="start"
                justifyContent="between"
                gap={2}
              >
                <Content
                  font="main-content-emphasis"
                  title={t("editor.instructions.title")}
                  description={t("editor.instructions.description")}
                />
                <InstructionsDisplayModeToggle
                  value={instructionsDisplayMode}
                  onChange={setInstructionsDisplayMode}
                />
              </Section>

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
                font="main-content-emphasis"
                title={t("editor.files.title")}
                description={t("editor.files.description")}
              />
              <Card border="solid" rounding={4}>
                <SkillFileTree
                  files={displayedFiles}
                  emptyMessage={
                    pendingFilesUpload?.entries === null
                      ? t("editor.files.pendingUpload.emptyMessage")
                      : undefined
                  }
                />
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
              </Card>
            </Section>
          </>
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      <ShareSkillModal
        mode="create"
        draft={sharingDraft}
        onSaveDraft={setCreationSharing}
        open={shareOpen}
        onClose={() => setShareOpen(false)}
      />

      <confirmUploadModal.Provider>
        {filesUploadToConfirm && (
          <ConfirmationModalLayout
            icon={SvgAlertTriangle}
            title={t("editor.confirmUpload.importTitle")}
            onClose={() => confirmUploadModal.toggle(false)}
            submit={
              <Button
                type="button"
                onClick={() => {
                  const upload = filesUploadToConfirm;
                  confirmUploadModal.toggle(false);
                  void applyFilesUpload(upload);
                }}
              >
                {t("editor.confirmUpload.importSubmit.label")}
              </Button>
            }
          >
            {t("editor.confirmUpload.importBody")}
          </ConfirmationModalLayout>
        )}
      </confirmUploadModal.Provider>

      <nameConflictModal.Provider>
        {conflictingSkillName && (
          <SkillNameConflictModal
            skillName={conflictingSkillName}
            onClose={() => nameConflictModal.toggle(false)}
            onConfirm={() => void handleSave(undefined, true)}
            pending={isSaving}
          />
        )}
      </nameConflictModal.Provider>

      <UnsavedChangesModal
        open={unsavedChanges.confirmationOpen}
        onCancel={unsavedChanges.cancelLeave}
        onDiscard={unsavedChanges.discardAndLeave}
      />
    </form>
  );
}
