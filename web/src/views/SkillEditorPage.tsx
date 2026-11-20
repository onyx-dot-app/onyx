"use client";

import { useNavigation } from "@opal/navigation";
import { useMemo, useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, Tooltip, useCreateModal } from "@opal/components";
import { SvgAlertTriangle, SvgBlocks } from "@opal/icons";
import {
  ConfirmationModalLayout,
  Section,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import { SWR_KEYS } from "@/lib/swr-keys";
import { refreshSkillListsChecked } from "@/lib/skills/cache";
import {
  createCustomSkillFromEditor,
  inspectSkillBundle,
  isSkillNameConflict,
} from "@/lib/skills/api";
import {
  mergeSkillFilesUploads,
  SkillMergeLimitError,
  type PreparedSkillFilesUpload,
} from "@/lib/skills/bundleUpload";
import {
  discardSkillCreationDraft,
  getSkillCreationDraft,
} from "@/lib/skills/creationDraft";
import {
  composeSkillMarkdown,
  parseSkillMarkdown,
} from "@/lib/customize/skillMarkdown";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { type InstructionsDisplayMode } from "@/sections/skills/InstructionsDisplayModeToggle";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillSharingSummary from "@/sections/skills/SkillSharingSummary";
import {
  emptySkillSharingDraft,
  serializeSkillSharing,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import SkillNameConflictModal from "@/sections/modals/skills/SkillNameConflictModal";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import { useSkillLimitCopy } from "@/lib/skills/hooks";
import { customizeTabHref, skillHref } from "@/lib/customize/paths";
import { BackLink } from "@/sections/customize/CustomizeDetailLayout";
import SkillBundleEditor, {
  bundleFiles,
  uploadPaths,
} from "@/sections/customize/SkillBundleEditor";

const EMPTY_SKILL_MD = composeSkillMarkdown({
  name: "",
  description: "",
  instructions: "",
});

interface SkillEditorPageProps {
  draftId?: string;
}

/** Creates a skill in the same files-and-SKILL.md editor as the Contents tab
 * of a skill. An existing skill is edited in place on that tab. */
export default function SkillEditorPage({ draftId }: SkillEditorPageProps) {
  const t = useTranslations("skills");
  const contentsCopy = useTranslations("customize.skillPage.contents");
  const tabCopy = useTranslations("customize.tabs");
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

  const [text, setText] = useState(() =>
    creationDraft
      ? composeSkillMarkdown({
          name: creationDraft.contents.name,
          description: creationDraft.contents.description,
          instructions: creationDraft.contents.instructions_markdown,
        })
      : EMPTY_SKILL_MD
  );
  // The first upload goes with the new skill; the rest are added after it.
  const [uploads, setUploads] = useState<PreparedSkillFilesUpload[]>(() =>
    creationDraft
      ? [
          {
            ...creationDraft.upload,
            entries: creationDraft.contents.files,
          },
        ]
      : []
  );
  const [removed, setRemoved] = useState<ReadonlySet<string>>(new Set());
  const [mode, setMode] = useState<InstructionsDisplayMode>("raw");
  const [creationSharing, setCreationSharing] =
    useState<SkillSharingDraft | null>(null);
  const [shareOpen, setShareOpen] = useState(false);
  const confirmUploadModal = useCreateModal();
  const nameConflictModal = useCreateModal();
  const [isSaving, setIsSaving] = useState(false);
  const [isPreparingFiles, setIsPreparingFiles] = useState(false);
  const [isUploadingFiles, setIsUploadingFiles] = useState(false);
  const [bundleToConfirm, setBundleToConfirm] =
    useState<PreparedSkillFilesUpload | null>(null);
  const [conflictingSkillName, setConflictingSkillName] = useState<
    string | null
  >(null);

  const parsed = parseSkillMarkdown(text);
  const name = parsed.ok ? parsed.name : "";
  const sharingDraft: SkillSharingDraft = {
    ...emptySkillSharingDraft(
      name || t("editor.header.createTitle"),
      user ? { id: user.id, email: user.email } : null
    ),
    ...creationSharing,
    name: name || t("editor.header.createTitle"),
  };

  const isDirty =
    text !== EMPTY_SKILL_MD ||
    uploads.length > 0 ||
    removed.size > 0 ||
    creationSharing !== null;
  const unsavedChanges = useUnsavedChangesGuard({
    isDirty,
    onDiscard: draftId ? () => discardSkillCreationDraft(draftId) : undefined,
  });

  // An inspected SKILL.md bundle replaces the text, so lock it meanwhile.
  const busy = isPreparingFiles || isUploadingFiles || isSaving;

  const createTooltip = isSaving
    ? t("editor.saveTooltip.savingSkill")
    : !parsed.ok
      ? contentsCopy(`errors.${parsed.error}`)
      : !parsed.name
        ? t("editor.saveTooltip.missingName")
        : !parsed.instructions
          ? t("editor.saveTooltip.missingInstructions")
          : undefined;
  const canCreate = !busy && createTooltip === undefined;

  const files = bundleFiles([], uploads, removed);

  function handleCancel() {
    if (busy) return;
    unsavedChanges.requestLeave(() =>
      navigation.go(customizeTabHref("skills"))
    );
  }

  async function applyBundle(upload: PreparedSkillFilesUpload) {
    setIsUploadingFiles(true);
    try {
      const bundle = await inspectSkillBundle(upload.file);
      setText(
        composeSkillMarkdown({
          name: bundle.name,
          description: bundle.description,
          instructions: bundle.instructions_markdown,
        })
      );
      setUploads([{ ...upload, entries: bundle.files }]);
      setRemoved(new Set());
    } catch (err) {
      console.error("Failed to inspect skill bundle", err);
      toast.error(
        err instanceof Error ? err.message : t("editor.toasts.inspectFailed")
      );
    } finally {
      setIsUploadingFiles(false);
    }
  }

  function handleAdd(upload: PreparedSkillFilesUpload) {
    if (upload.containsSkillMd) {
      if (isDirty) {
        setBundleToConfirm(upload);
        confirmUploadModal.toggle(true);
      } else {
        void applyBundle(upload);
      }
      return;
    }
    setUploads((current) => [...current, upload]);
    const paths = new Set(uploadPaths(upload));
    setRemoved(
      (current) => new Set([...current].filter((path) => !paths.has(path)))
    );
  }

  async function handleSave(
    event?: FormEvent<HTMLFormElement>,
    createDisabled = false
  ) {
    event?.preventDefault();
    if (!parsed.ok || (!canCreate && !createDisabled)) return;
    setIsSaving(true);
    try {
      // One upload with every file that is left, so the skill is created,
      // shared and published as one version. An upload whose files were all
      // removed (a ZIP lists as one row) is left out whole.
      const live = uploads.filter((item) =>
        uploadPaths(item).some((path) => !removed.has(path))
      );
      const [only] = live;
      const upload =
        live.length === 1 &&
        only &&
        !uploadPaths(only).some((path) => removed.has(path))
          ? only.file
          : await mergeSkillFilesUploads(live, removed);
      const created = await createCustomSkillFromEditor(
        {
          name: parsed.name,
          description: parsed.description,
          instructions_markdown: parsed.instructions,
          auto_enable: !createDisabled,
          sharing: creationSharing
            ? serializeSkillSharing(creationSharing, canManageOrgSkills)
            : undefined,
        },
        upload
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
        setConflictingSkillName(parsed.name);
        nameConflictModal.toggle(true);
        return;
      }
      console.error("Failed to save skill", err);
      toast.error(
        err instanceof SkillMergeLimitError
          ? t("editor.toasts.mergeLimit", { limit: err.limit, max: err.max })
          : describeError(err, t("editor.toasts.saveFailed"))
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <form
      className="h-full w-full"
      data-testid="SkillEditorPage/container"
      onSubmit={handleSave}
    >
      <SettingsLayouts.Root width="lg">
        <SettingsLayouts.Header
          back={
            <BackLink
              to={customizeTabHref("skills")}
              label={tabCopy("skills")}
            />
          }
          icon={SvgBlocks}
          title={name || t("editor.header.createTitle")}
          description={t("editor.header.createDescription")}
          stackActionsOnMobile
          actions={[
            <Button
              key="cancel"
              type="button"
              prominence="secondary"
              onClick={handleCancel}
            >
              {t("editor.header.cancel")}
            </Button>,
            <Tooltip key="save" tooltip={createTooltip} side="bottom">
              <Button disabled={!canCreate} type="submit">
                {isSaving
                  ? t("editor.header.save.pendingLabel")
                  : t("editor.header.save.label")}
              </Button>
            </Tooltip>,
          ]}
        />

        <SettingsLayouts.Body>
          <Section gap={4} alignItems="stretch" height="auto">
            <SkillBundleEditor
              files={files}
              editing
              text={text}
              onTextChange={setText}
              preview={parsed.ok ? parsed.instructions : text}
              mode={mode}
              onModeChange={setMode}
              busy={busy}
              onAdd={handleAdd}
              onRemove={(path) =>
                setRemoved((current) => new Set([...current, path]))
              }
              onPreparingChange={setIsPreparingFiles}
              addedFileNote={t("editor.files.addedOnCreate")}
            />
            <SkillSharingSummary
              title={t("editor.creationAccess.title")}
              draft={sharingDraft}
              count={1}
              configureLabel={t("editor.management.sharing.edit.label")}
              disabled={busy}
              onConfigure={() => setShareOpen(true)}
            />
          </Section>
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
        {bundleToConfirm && (
          <ConfirmationModalLayout
            icon={SvgAlertTriangle}
            title={t("editor.confirmUpload.importTitle")}
            onClose={() => confirmUploadModal.toggle(false)}
            submit={
              <Button
                type="button"
                onClick={() => {
                  const upload = bundleToConfirm;
                  confirmUploadModal.toggle(false);
                  void applyBundle(upload);
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
