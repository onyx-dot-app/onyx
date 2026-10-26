"use client";

import isEqual from "lodash/isEqual";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Modal } from "@opal/components";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import type { AppActionPoliciesView } from "@/lib/plugins/types";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import PolicyEditor from "@/sections/actions/PolicyEditor";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";

interface TaskAppActionsModalProps {
  app: AppActionPoliciesView;
  policies: Record<string, ActionPolicy>;
  onClose: () => void;
  onSave: (policies: Record<string, ActionPolicy>) => void;
}

export default function TaskAppActionsModal({
  app,
  policies: initialPolicies,
  onClose,
  onSave,
}: TaskAppActionsModalProps) {
  const t = useTranslations("craft.actionPolicies");
  const [policies, setPolicies] = useState(initialPolicies);
  const isDirty = !isEqual(policies, initialPolicies);
  const unsavedChanges = useUnsavedChangesGuard({ isDirty });
  function requestClose() {
    if (unsavedChanges.confirmationOpen) unsavedChanges.cancelLeave();
    else unsavedChanges.requestLeave(onClose);
  }
  function handleDismiss(event: Event) {
    const alreadyPrevented = event.defaultPrevented;
    event.preventDefault();
    if (!alreadyPrevented) requestClose();
  }
  return (
    <Modal
      open
      onOpenChange={(open) => {
        if (!open) requestClose();
      }}
    >
      <PluginModalContent
        onInteractOutside={handleDismiss}
        onEscapeKeyDown={handleDismiss}
      >
        {unsavedChanges.confirmationOpen ? (
          <UnsavedChangesModalContent
            onCancel={unsavedChanges.cancelLeave}
            onDiscard={unsavedChanges.discardAndLeave}
          />
        ) : null}
        <div
          hidden={unsavedChanges.confirmationOpen}
          className={unsavedChanges.confirmationOpen ? "hidden" : "contents"}
        >
          <Modal.Header
            title={t("appTitle", { name: app.name })}
            description={t("taskModalDescription")}
            onClose={requestClose}
          />
          <Modal.Body>
            <PolicyEditor
              showTitle={false}
              items={app.actions.map((action) => ({
                id: action.action_id,
                name: action.normalised_name,
                description: action.description,
                defaultPolicy: action.effective_policy,
                editable: action.editable,
                lockReason: action.lock_reason,
              }))}
              policies={policies}
              onChange={setPolicies}
              onReset={() =>
                setPolicies((current) => ({
                  ...current,
                  ...Object.fromEntries(
                    app.actions
                      .filter((action) => action.editable)
                      .map((action) => [
                        action.action_id,
                        action.workspace_policy,
                      ])
                  ),
                }))
              }
              resetLabel={t("resetAll")}
            />
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={requestClose}>
              {t("cancel")}
            </Button>

            <Button disabled={!isDirty} onClick={() => onSave(policies)}>
              {t("saveChanges")}
            </Button>
          </Modal.Footer>
        </div>
      </PluginModalContent>
    </Modal>
  );
}
