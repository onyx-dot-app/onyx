"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  MessageCard,
  Modal,
  Text,
  useCreateModal,
} from "@opal/components";
import { SvgUploadCloud } from "@opal/icons";
import { inspectSkillBundle, uploadSkillBundles } from "@/lib/skills/api";
import type { PreparedSkillBundle } from "@/lib/skills/bundleUpload";
import type { SkillCreationDraft } from "@/lib/skills/creationDraft";
import SkillBundlePicker from "@/sections/skills/SkillBundlePicker";
import { Section } from "@opal/layouts";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillSharingSummary from "@/sections/skills/SkillSharingSummary";
import {
  emptySkillSharingDraft,
  serializeSkillSharing,
  type SkillSharingDraft,
} from "@/lib/skills/sharing";
import type { GitHubSkillsImportResult } from "@/lib/skills/types";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";

interface CreateSkillModalProps {
  open: boolean;
  onClose: () => void;
  onContinue: (draft: SkillCreationDraft) => void;
  onImported?: () => void;
  validateDraft?: (draft: SkillCreationDraft) => string | null;
}

interface CreateSkillModalContentProps extends Omit<
  CreateSkillModalProps,
  "open" | "onClose"
> {
  hidden?: boolean;
  onRequestClose: () => void;
  onBusyChange?: (busy: boolean) => void;
  onDirtyChange?: (dirty: boolean) => void;
  preserveDraftOnContinue?: boolean;
}

export function CreateSkillModalContent({
  hidden = false,
  onRequestClose,
  onContinue,
  onImported,
  onBusyChange,
  onDirtyChange,
  preserveDraftOnContinue = false,
  validateDraft,
}: CreateSkillModalContentProps) {
  const t = useTranslations("skills.modals");
  const [bundle, setBundle] = useState<PreparedSkillBundle | null>(null);
  const [preparing, setPreparing] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const busy = preparing || inspecting;
  const { user } = useUser();
  const { isGlobalHolder: canManageCompanySkills } = usePermissionAuthority(
    Permission.MANAGE_SKILLS
  );
  const [batchFiles, setBatchFiles] = useState<File[]>([]);
  const [result, setResult] = useState<GitHubSkillsImportResult | null>(null);
  const [sharing, setSharing] = useState<SkillSharingDraft | null>(null);
  const sharingModal = useCreateModal();
  const sharingDraft =
    sharing ??
    emptySkillSharingDraft(
      t("create.batch.title"),
      user ? { id: user.id, email: user.email } : null
    );

  useEffect(() => {
    onBusyChange?.(busy);
  }, [busy, onBusyChange]);

  function reset() {
    setBundle(null);
    setBatchFiles([]);
    setSharing(null);
    setResult(null);
    setErrorMessage(null);
    onDirtyChange?.(false);
  }

  function handleClose() {
    if (busy) return;
    onRequestClose();
  }

  async function handleContinue() {
    if (busy || result || (!bundle && batchFiles.length === 0)) return;
    if (batchFiles.length > 0) {
      setInspecting(true);
      setErrorMessage(null);
      try {
        const imported = await uploadSkillBundles(
          batchFiles,
          sharing
            ? serializeSkillSharing(sharing, canManageCompanySkills)
            : undefined
        );
        setResult(imported);
        onDirtyChange?.(false);
        if (imported.imported.length > 0) onImported?.();
      } catch (error) {
        setErrorMessage(
          error instanceof Error ? error.message : t("create.readError.message")
        );
      } finally {
        setInspecting(false);
      }
      return;
    }
    if (!bundle) return;
    setInspecting(true);
    setErrorMessage(null);
    try {
      const contents = await inspectSkillBundle(bundle.file);
      const draft: SkillCreationDraft = {
        contents,
        upload: {
          file: bundle.file,
          displayName: bundle.displayName,
          entries: contents.files,
          containsSkillMd: true,
        },
      };
      const validationError = validateDraft?.(draft);
      if (validationError) {
        setErrorMessage(validationError);
        return;
      }
      if (!preserveDraftOnContinue) reset();
      onContinue(draft);
    } catch (error) {
      console.error("Failed to inspect skill bundle", error);
      setErrorMessage(
        error instanceof Error ? error.message : t("create.readError.message")
      );
    } finally {
      setInspecting(false);
    }
  }

  if (hidden) return null;

  return (
    <>
      <Modal.Header
        icon={SvgUploadCloud}
        title={t("create.header.title")}
        description={t("create.header.description")}
        onClose={handleClose}
      />
      <Modal.Body>
        {!result && (
          <SkillBundlePicker
            value={bundle}
            disabled={inspecting}
            onPreparingChange={setPreparing}
            onChange={(nextBundle) => {
              setBundle(nextBundle);
              setBatchFiles([]);
              setErrorMessage(null);
              onDirtyChange?.(nextBundle !== null);
            }}
            onBatchChange={
              onImported
                ? (files) => {
                    setBatchFiles(files);
                    setBundle(null);
                    setErrorMessage(null);
                    onDirtyChange?.(true);
                  }
                : undefined
            }
            onError={(message) => {
              setBundle(null);
              setBatchFiles([]);
              setErrorMessage(message);
              onDirtyChange?.(false);
            }}
          />
        )}
        {!result && batchFiles.length > 0 && (
          <SkillSharingSummary
            title={t("create.batch.selected", { count: batchFiles.length })}
            draft={sharingDraft}
            count={batchFiles.length}
            configureLabel={t("importGithub.sharing.configureButton")}
            disabled={busy}
            onConfigure={() => sharingModal.toggle(true)}
          >
            <Section height="auto" className="max-h-24 overflow-y-auto">
              <Text font="secondary-body" color="text-03">
                {batchFiles.map((file) => file.name).join(", ")}
              </Text>
            </Section>
          </SkillSharingSummary>
        )}
        {result && (
          <Section gap={2} height="auto" alignItems="stretch">
            <MessageCard
              variant={
                result.imported.length === 0
                  ? "error"
                  : result.not_imported.length > 0
                    ? "warning"
                    : "success"
              }
              title={t("create.batch.result", {
                imported: result.imported.length,
                failed: result.not_imported.length,
              })}
            />
            {result.imported.map((item) => (
              <Section
                key={item.skill.id}
                height="auto"
                alignItems="stretch"
                gap={1}
              >
                <Text font="secondary-body">{item.skill.name}</Text>
                {item.disabled_reason && (
                  <Text font="secondary-body" color="text-03">
                    {item.disabled_reason}
                  </Text>
                )}
              </Section>
            ))}
            {result.not_imported.map((item) => (
              <Text
                key={item.path}
                font="secondary-body"
                color="status-error-05"
              >
                {t("create.batch.failure", {
                  name: item.name,
                  reason: item.reason,
                })}
              </Text>
            ))}
          </Section>
        )}
        {!result && (
          <div className="mt-3">
            <Text as="p" font="main-ui-body" color="text-02">
              {t("create.requirements.title")}
            </Text>
            <ul className="mt-1 list-disc space-y-1 ps-5">
              <Text as="li" font="secondary-body" color="text-03">
                {t("create.requirements.frontmatter")}
              </Text>
              <Text as="li" font="secondary-body" color="text-03">
                {t("create.requirements.zip")}
              </Text>
              <Text as="li" font="secondary-body" color="text-03">
                {onImported
                  ? t("create.batch.requirement")
                  : t("create.requirements.singleSkill")}
              </Text>
            </ul>
          </div>
        )}
        {errorMessage && (
          <div role="alert" className="mt-2">
            <Text as="p" font="secondary-body" color="status-error-05">
              {errorMessage}
            </Text>
          </div>
        )}
      </Modal.Body>
      <Modal.Footer>
        {result ? (
          <Button onClick={handleClose}>
            {t("importGithub.doneButton.label")}
          </Button>
        ) : (
          <>
            <Button
              prominence="secondary"
              disabled={busy}
              onClick={handleClose}
            >
              {t("create.cancelButton.label")}
            </Button>
            <Button
              disabled={busy || (!bundle && batchFiles.length === 0)}
              onClick={() => void handleContinue()}
              icon={SvgUploadCloud}
            >
              {inspecting
                ? batchFiles.length > 0
                  ? t("importGithub.submitButton.importingLabel")
                  : t("create.continueButton.loadingLabel")
                : batchFiles.length > 0
                  ? t("importGithub.submitButton.importLabel", {
                      count: batchFiles.length,
                    })
                  : t("create.continueButton.label")}
            </Button>
          </>
        )}
      </Modal.Footer>
      <sharingModal.Provider>
        <ShareSkillModal
          mode="create"
          open
          draft={sharingDraft}
          onSaveDraft={setSharing}
          onClose={() => sharingModal.toggle(false)}
        />
      </sharingModal.Provider>
    </>
  );
}

export default function CreateSkillModal({
  open,
  onClose,
  onContinue,
  onImported,
  validateDraft,
}: CreateSkillModalProps) {
  const [busy, setBusy] = useState(false);

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && !busy && onClose()}>
      <Modal.Content width="sm" maxHeight="80dvh">
        {open && (
          <CreateSkillModalContent
            onRequestClose={onClose}
            onContinue={onContinue}
            onImported={onImported}
            onBusyChange={setBusy}
            validateDraft={validateDraft}
          />
        )}
      </Modal.Content>
    </Modal>
  );
}
