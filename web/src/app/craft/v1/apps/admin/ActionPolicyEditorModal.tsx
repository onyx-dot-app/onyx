"use client";

import { useId, useState } from "react";
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
import { InputVertical } from "@opal/layouts";
import PluginModalContent from "@/views/admin/PluginsPage/PluginModalContent";
import PolicyEditor, {
  type PolicyEditorItem,
  UserManagementSwitch,
} from "@/sections/actions/PolicyEditor";
export type { PolicyEditorItem } from "@/sections/actions/PolicyEditor";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";
import CraftAppEditorTabs from "@/sections/plugins/CraftAppEditorTabs";
import type { IconFunctionComponent, RichStr } from "@opal/types";

// A required text input the app needs before it can be saved
// (name, credentials, …).
export interface EditorField {
  key: string;
  label: string;
  description: string;
  placeholder: string;
  secret: boolean;
  section: "configuration" | "authentication";
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
  displayUrl?: string;
  icon?: IconFunctionComponent;
  authenticationInstructions?: string | RichStr;
  /** Shown in place of field inputs when there is nothing to type in. */
  note?: string | RichStr;
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
  skillsContent?: (
    requestLeave: (navigate: () => void) => void
  ) => React.ReactNode;
  autoFocusFirstField?: boolean;
  /** Allow create flows to persist valid defaults without an artificial edit. */
  allowPristineSave?: boolean;
  /** Keep the modal mounted when save advances its caller to another step. */
  closeAfterSave?: boolean;
}

/** Built-in app editor. Mount only while open; initial values are read once. */
export default function ActionPolicyEditorModal({
  alternateContent,
  alternateContentConfirmationOpen = false,
  isAdditionalContentDirty = false,
  usersCanManagePolicies,
  onUsersCanManagePoliciesChange,
  onClose,
  title,
  displayUrl,
  icon,
  authenticationInstructions,
  note,
  fields,
  initialFieldValues,
  policyItems,
  initialPolicies,
  emptyPoliciesMessage,
  saveLabel,
  onSave,
  skillsContent,
  autoFocusFirstField = true,
  allowPristineSave = false,
  closeAfterSave = true,
}: ActionPolicyEditorModalProps) {
  const t = useTranslations("craft.apps.policyEditor");
  const fieldId = useId();
  const focusFirstField =
    useFocusOnMount<HTMLInputElement>(autoFocusFirstField);
  const [fieldValues, setFieldValues] = useState<Record<string, string>>({
    ...initialFieldValues,
  });
  const [policies, setPolicies] = useState<Record<string, ActionPolicy>>({
    ...initialPolicies,
  });
  const [isSaving, setIsSaving] = useState(false);
  const [tab, setTab] = useState("configuration");
  const [error, setError] = useState<string | null>(null);
  const fieldsFilled = fields.every(
    (field) => (fieldValues[field.key] ?? "").trim().length > 0
  );
  const fieldsDirty = !isEqual(fieldValues, initialFieldValues);
  const policiesDirty = !isEqual(policies, initialPolicies);
  const isDirty = fieldsDirty || policiesDirty || isAdditionalContentDirty;
  // Closing never asks to discard edits; leaving runs at once.
  const requestLeave = (navigate: () => void) => navigate();
  const confirmationOpen = alternateContentConfirmationOpen;
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

  function requestClose() {
    if (isSaving) return;
    onClose();
  }

  function handleDismiss(event: Event) {
    const preventedByModal = event.defaultPrevented;
    event.preventDefault();
    if (preventedByModal || isSaving) return;
    requestClose();
  }

  function renderFields(section: EditorField["section"]) {
    return fields
      .filter((field) => field.section === section)
      .map((field) => {
        const Input = field.secret ? InputPasswordTypeIn : InputTypeIn;
        return (
          <InputVertical
            key={field.key}
            title={field.label}
            subDescription={field.description}
            withLabel={`${fieldId}-${field.key}`}
          >
            <Input
              id={`${fieldId}-${field.key}`}
              aria-label={field.label}
              ref={field === fields[0] ? focusFirstField : undefined}
              value={fieldValues[field.key] ?? ""}
              disabled={isSaving}
              onChange={(event) =>
                setFieldValues((previous) => ({
                  ...previous,
                  [field.key]: event.target.value,
                }))
              }
              placeholder={field.placeholder}
            />
          </InputVertical>
        );
      });
  }

  return (
    <Modal open>
      <PluginModalContent
        onOpenAutoFocus={(event) => {
          if (!autoFocusFirstField) event.preventDefault();
        }}
        onInteractOutside={handleDismiss}
        onEscapeKeyDown={handleDismiss}
      >
        {alternateContent ? (
          alternateContent({
            requestLeave,
            hidden: confirmationOpen,
          })
        ) : (
          <>
            <Modal.Header
              title={title}
              description={displayUrl || undefined}
              icon={icon}
              onClose={requestClose}
            />
            <Modal.Body alignItems="stretch">
              <div className="flex flex-col gap-3">
                <CraftAppEditorTabs
                  value={tab}
                  onValueChange={setTab}
                  busy={isSaving}
                  configuration={
                    <>
                      {fields.some(
                        (field) => field.section === "configuration"
                      ) ? (
                        renderFields("configuration")
                      ) : (
                        <Text font="main-ui-action">{title}</Text>
                      )}
                      {usersCanManagePolicies !== undefined &&
                        onUsersCanManagePoliciesChange && (
                          <UserManagementSwitch
                            value={usersCanManagePolicies}
                            onChange={onUsersCanManagePoliciesChange}
                            disabled={isSaving}
                          />
                        )}
                    </>
                  }
                  authentication={
                    <>
                      {note && (
                        <Text font="secondary-body" color="text-03">
                          {note}
                        </Text>
                      )}
                      {authenticationInstructions && (
                        <Text font="secondary-body" color="text-03">
                          {authenticationInstructions}
                        </Text>
                      )}
                      {renderFields("authentication")}
                    </>
                  }
                  tools={
                    <>
                      {policyItems === undefined ? (
                        <Text font="main-content-body" color="text-03">
                          {t("loading.label")}
                        </Text>
                      ) : policyItems.length === 0 ? (
                        <Text font="secondary-body" color="text-03">
                          {emptyPoliciesMessage}
                        </Text>
                      ) : (
                        <PolicyEditor
                          showTitle={false}
                          disabled={isSaving}
                          items={policyItems}
                          policies={policies}
                          onChange={setPolicies}
                        />
                      )}
                    </>
                  }
                  skills={skillsContent?.(requestLeave)}
                />

                {error && (
                  <div role="alert">
                    <Text font="secondary-body" color="status-error-05">
                      {error}
                    </Text>
                  </div>
                )}
              </div>
            </Modal.Body>
            <Modal.Footer>
              <div className="flex justify-end gap-2 w-full">
                <Button
                  prominence="secondary"
                  onClick={onClose}
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
      </PluginModalContent>
    </Modal>
  );
}
