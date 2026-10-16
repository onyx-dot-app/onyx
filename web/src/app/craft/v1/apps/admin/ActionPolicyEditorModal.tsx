"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import isEqual from "lodash/isEqual";
import {
  Button,
  InputTypeIn,
  Modal,
  InputPasswordTypeIn,
  Text,
} from "@opal/components";
import {
  ActionPolicyEditor,
  type ActionPolicyRow,
} from "@/app/craft/v1/apps/action-policies/ActionPolicyRows";
import UserManagementSwitch from "@/app/craft/v1/apps/action-policies/UserManagementSwitch";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";

// One agent-callable capability whose approval policy an admin can set —
// an external-app action or an MCP tool.
export type PolicyEditorItem = ActionPolicyRow;

// A required text input the app needs before it can be saved
// (name, credentials, …).
export interface EditorField {
  key: string;
  label: string;
  description: string;
  placeholder: string;
  secret: boolean;
}

interface ActionPolicyEditorModalProps {
  /** Alternate view rendered inside the same modal surface. It remains
   * mounted while the discard confirmation is visible so local draft state
   * survives cancellation. */
  alternateContent?: (context: {
    requestLeave: (navigate: () => void) => void;
    hidden: boolean;
  }) => React.ReactNode;
  alternateContentConfirmationOpen?: boolean;
  isAdditionalContentDirty?: boolean;
  usersCanManagePolicies?: boolean;
  onUsersCanManagePoliciesChange?: (value: boolean) => void;
  onClose: () => void;
  title: string;
  description: string;
  /** Shown in place of field inputs when there is nothing to type in. */
  note?: string;
  fields: EditorField[];
  initialFieldValues: Record<string, string>;
  /** Undefined while the capability list is still loading. */
  policyItems: PolicyEditorItem[] | undefined;
  initialPolicies: Record<string, ActionPolicy>;
  /** Shown when the capability list resolves to empty. */
  emptyPoliciesMessage: string;
  saveLabel: string;
  /** Persist the edit; throw to surface the failure inside the modal. */
  onSave: (
    fieldValues: Record<string, string>,
    policies: Record<string, ActionPolicy>
  ) => Promise<void>;
  bodyAfterPolicies?: (
    requestLeave: (navigate: () => void) => void
  ) => React.ReactNode;
  autoFocusFirstField?: boolean;
  /** Allow create flows to persist valid defaults without an artificial edit. */
  allowPristineSave?: boolean;
  /** Keep the modal mounted when save advances its caller to another step. */
  closeAfterSave?: boolean;
}

/** The one edit dialog for everything the Craft agent can be granted.
 * Callers (external apps, MCP servers) normalize their data into fields +
 * policy items and supply the save call; the UI is identical for both.
 * Mount it only while open — initial values are read once. */
export default function ActionPolicyEditorModal({
  usersCanManagePolicies,
  onUsersCanManagePoliciesChange,
  alternateContent,
  alternateContentConfirmationOpen = false,
  isAdditionalContentDirty = false,
  onClose,
  title,
  description,
  note,
  fields,
  initialFieldValues,
  policyItems,
  initialPolicies,
  emptyPoliciesMessage,
  saveLabel,
  onSave,
  bodyAfterPolicies,
  autoFocusFirstField = true,
  allowPristineSave = false,
  closeAfterSave = true,
}: ActionPolicyEditorModalProps) {
  const t = useTranslations("craft.apps.policyEditor");
  const tPolicies = useTranslations("craft.actionPolicies");
  const focusFirstField =
    useFocusOnMount<HTMLInputElement>(autoFocusFirstField);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({
    ...initialFieldValues,
  });
  const [policies, setPolicies] = useState<Record<string, ActionPolicy>>({
    ...initialPolicies,
  });
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fieldsFilled = fields.every(
    (field) => (fieldValues[field.key] ?? "").trim().length > 0
  );
  const fieldsDirty = !isEqual(fieldValues, initialFieldValues);
  const policiesDirty = !isEqual(policies, initialPolicies);
  const isDirty = fieldsDirty || policiesDirty || isAdditionalContentDirty;
  const unsavedChanges = useUnsavedChangesGuard({ isDirty });
  const confirmationOpen =
    alternateContentConfirmationOpen || unsavedChanges.confirmationOpen;
  const canSave =
    fieldsFilled &&
    policyItems !== undefined &&
    !isSaving &&
    (allowPristineSave || isDirty);

  async function save() {
    setIsSaving(true);
    setError(null);
    try {
      await onSave(fieldValues, policies);
      if (closeAfterSave) onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setIsSaving(false);
    }
  }

  function handleDismiss(event: Event) {
    const preventedByModal = event.defaultPrevented;
    event.preventDefault();
    if (preventedByModal || isSaving) return;
    if (unsavedChanges.confirmationOpen) {
      unsavedChanges.cancelLeave();
      return;
    }
    if (alternateContent) {
      onClose();
    } else {
      unsavedChanges.requestLeave(onClose);
    }
  }

  const confirmationContent = unsavedChanges.confirmationOpen ? (
    <UnsavedChangesModalContent
      onCancel={unsavedChanges.cancelLeave}
      onDiscard={unsavedChanges.discardAndLeave}
    />
  ) : null;

  return (
    <Modal open>
      <Modal.Content
        width={confirmationOpen || alternateContent ? "sm" : "lg"}
        height={confirmationOpen || alternateContent ? "fit" : "lg"}
        onOpenAutoFocus={(event) => {
          if (!autoFocusFirstField) event.preventDefault();
        }}
        preventAccidentalClose={!confirmationOpen}
        onInteractOutside={handleDismiss}
        onEscapeKeyDown={handleDismiss}
      >
        {alternateContent ? (
          <>
            {alternateContent({
              requestLeave: unsavedChanges.requestLeave,
              hidden: confirmationOpen,
            })}
            {confirmationContent}
          </>
        ) : confirmationContent ? (
          confirmationContent
        ) : (
          <>
            <Modal.Header title={title} description={description} />
            <Modal.Body>
              <div className="flex flex-col gap-3">
                {note && (
                  <Text font="secondary-body" color="text-03">
                    {note}
                  </Text>
                )}

                {fields.map((field) => {
                  const Input = field.secret
                    ? InputPasswordTypeIn
                    : InputTypeIn;
                  return (
                    <div key={field.key} className="flex flex-col gap-1">
                      <Text font="main-ui-action">{field.label}</Text>
                      <Input
                        ref={field === fields[0] ? focusFirstField : undefined}
                        value={fieldValues[field.key] ?? ""}
                        onChange={(e) =>
                          setFieldValues((prev) => ({
                            ...prev,
                            [field.key]: e.target.value,
                          }))
                        }
                        placeholder={field.placeholder}
                      />
                      <Text font="secondary-body" color="text-03">
                        {field.description}
                      </Text>
                    </div>
                  );
                })}

                {usersCanManagePolicies !== undefined &&
                  onUsersCanManagePoliciesChange && (
                    <UserManagementSwitch
                      disabled={isSaving}
                      value={usersCanManagePolicies}
                      onChange={onUsersCanManagePoliciesChange}
                    />
                  )}
                {policyItems === undefined ? (
                  <Text font="main-content-body" color="text-03">
                    {t("loading.label")}
                  </Text>
                ) : policyItems.length === 0 ? (
                  <Text font="secondary-body" color="text-03">
                    {emptyPoliciesMessage}
                  </Text>
                ) : (
                  <ActionPolicyEditor
                    items={policyItems}
                    policies={policies}
                    onChange={setPolicies}
                    resetLabel={tPolicies("resetDefaults")}
                    disabled={isSaving}
                    onReset={() =>
                      setPolicies(
                        Object.fromEntries(
                          policyItems.map((item) => [
                            item.id,
                            item.fallbackPolicy,
                          ])
                        )
                      )
                    }
                  />
                )}

                {bodyAfterPolicies?.(unsavedChanges.requestLeave)}

                {error && (
                  <Text font="secondary-body" color="text-03">
                    {error}
                  </Text>
                )}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <div className="flex justify-end gap-2 w-full">
                <Button
                  prominence="secondary"
                  onClick={() => unsavedChanges.requestLeave(onClose)}
                  disabled={isSaving}
                >
                  {t("cancelButton")}
                </Button>
                <Button onClick={save} disabled={!canSave}>
                  {isSaving ? t("savingButton") : saveLabel}
                </Button>
              </div>
            </Modal.Footer>
          </>
        )}
      </Modal.Content>
    </Modal>
  );
}
