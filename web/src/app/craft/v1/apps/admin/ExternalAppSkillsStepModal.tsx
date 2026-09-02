"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import isEqual from "lodash/isEqual";
import { Button, MessageCard, Modal } from "@opal/components";
import type { ExternalAppAdminResponse } from "@/app/craft/v1/apps/registry";
import { updateExternalApp } from "@/app/craft/services/externalAppsService";
import AssociatedSkillsEditor from "@/app/craft/v1/apps/admin/AssociatedSkillsEditor";
import {
  skillEditorUrlForApp,
  skillEditUrlForApp,
} from "@/app/craft/v1/apps/admin/skillAssociationNavigation";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { useSyncedAssociatedSkillIds } from "@/lib/externalApps/hooks";
import {
  stageSkillCreationDraft,
  type SkillCreationDraft,
} from "@/lib/skills/creationDraft";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import { CreateSkillModalContent } from "@/sections/modals/skills/CreateSkillModal";
import useSkillUploadModal from "@/sections/modals/skills/useSkillUploadModal";

interface ExternalAppSkillsStepModalProps {
  app: ExternalAppAdminResponse;
  onClose: () => void;
  onSaved: () => void;
}

/** Optional association step shown after an external app becomes durable. */
export default function ExternalAppSkillsStepModal({
  app,
  onClose,
  onSaved,
}: ExternalAppSkillsStepModalProps) {
  const t = useTranslations("craft.apps.skillsStep");
  const tApps = useTranslations("craft.apps");
  const router = useRouter();
  const [selectedSkillIds, setSelectedSkillIds] =
    useSyncedAssociatedSkillIds(app);
  const upload = useSkillUploadModal();
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isDirty = !isEqual(
    new Set(selectedSkillIds),
    new Set(app.associated_skills.map((skill) => skill.id))
  );
  const unsavedChanges = useUnsavedChangesGuard({ isDirty });

  function navigateToSkillEditor(draft?: SkillCreationDraft) {
    router.push(
      skillEditorUrlForApp(
        app,
        draft ? stageSkillCreationDraft(draft) : undefined
      )
    );
  }

  function handleDismiss(event: Event) {
    const preventedByModal = event.defaultPrevented;
    event.preventDefault();
    if (preventedByModal || isSaving) return;
    if (unsavedChanges.confirmationOpen) {
      unsavedChanges.cancelLeave();
    } else if (upload.isOpen) {
      upload.requestDismiss();
    } else {
      unsavedChanges.requestLeave(onClose);
    }
  }

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      await updateExternalApp(app.id, {
        associated_skill_ids: selectedSkillIds,
      });
      onSaved();
      onClose();
    } catch (saveError) {
      setError(
        saveError instanceof Error ? saveError.message : String(saveError)
      );
    } finally {
      setIsSaving(false);
    }
  }

  const confirmationOpen =
    upload.confirmationOpen || unsavedChanges.confirmationOpen;
  const confirmationContent = upload.confirmationOpen ? (
    <UnsavedChangesModalContent
      onCancel={upload.cancelDiscard}
      onDiscard={upload.discardAndClose}
    />
  ) : unsavedChanges.confirmationOpen ? (
    <UnsavedChangesModalContent
      onCancel={unsavedChanges.cancelLeave}
      onDiscard={unsavedChanges.discardAndLeave}
    />
  ) : null;

  return (
    <Modal open>
      <Modal.Content
        width={confirmationOpen || upload.isOpen ? "sm" : "lg"}
        height={confirmationOpen || upload.isOpen ? "fit" : "lg"}
        preventAccidentalClose={!confirmationOpen}
        onInteractOutside={handleDismiss}
        onEscapeKeyDown={handleDismiss}
      >
        {upload.isOpen ? (
          <>
            <CreateSkillModalContent
              hidden={confirmationOpen}
              onRequestClose={upload.requestDismiss}
              onBusyChange={upload.setBusy}
              onDirtyChange={upload.setDirty}
              preserveDraftOnContinue
              validateDraft={(draft) =>
                app.associated_skills.some(
                  (skill) => skill.name === draft.contents.name
                )
                  ? tApps("errors.duplicateSkillName", {
                      appName: app.name,
                      skillName: draft.contents.name,
                    })
                  : null
              }
              onContinue={(draft) =>
                unsavedChanges.requestLeave(() => navigateToSkillEditor(draft))
              }
            />
            {confirmationContent}
          </>
        ) : confirmationContent ? (
          confirmationContent
        ) : (
          <>
            <Modal.Header
              title={t("title", { name: app.name })}
              description={t("description")}
            />
            <Modal.Body>
              <div className="flex flex-col gap-3">
                <AssociatedSkillsEditor
                  app={app}
                  selectedSkillIds={selectedSkillIds}
                  onChange={setSelectedSkillIds}
                  onOpenSkill={(skillId) =>
                    unsavedChanges.requestLeave(() =>
                      router.push(skillEditUrlForApp(skillId, app))
                    )
                  }
                  onCreateSkill={() =>
                    unsavedChanges.requestLeave(() => navigateToSkillEditor())
                  }
                  onUploadSkill={upload.open}
                />
                {error && (
                  <MessageCard
                    variant="error"
                    title={t("errors.saveFailedTitle")}
                    description={error}
                  />
                )}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <div className="flex w-full justify-end gap-2">
                <Button
                  prominence="secondary"
                  onClick={() => unsavedChanges.requestLeave(onClose)}
                  disabled={isSaving}
                >
                  {t("skipButton")}
                </Button>
                <Button
                  disabled={isSaving || !isDirty}
                  onClick={() => void save()}
                >
                  {isSaving ? t("savingButton") : t("saveButton")}
                </Button>
              </div>
            </Modal.Footer>
          </>
        )}
      </Modal.Content>
    </Modal>
  );
}
