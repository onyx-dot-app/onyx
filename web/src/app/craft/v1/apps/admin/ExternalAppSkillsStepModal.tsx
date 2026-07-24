"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
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
      upload.dismiss();
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
      onDiscard={upload.confirmDiscard}
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
              onClose={upload.close}
              onBusyChange={upload.setBusy}
              onDirtyChange={upload.setDirty}
              preserveDraftOnContinue
              validateDraft={(draft) =>
                app.associated_skills.some(
                  (skill) => skill.name === draft.contents.name
                )
                  ? `App “${app.name}” already has an associated skill named “${draft.contents.name}”. Upload a skill with a different name.`
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
              title={`Add skills to ${app.name}`}
              description="Optional — associate existing skills or create one for this app."
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
                    title="Couldn't save"
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
                  Skip for now
                </Button>
                <Button
                  disabled={isSaving || !isDirty}
                  onClick={() => void save()}
                >
                  {isSaving ? "Saving…" : "Save skills"}
                </Button>
              </div>
            </Modal.Footer>
          </>
        )}
      </Modal.Content>
    </Modal>
  );
}
