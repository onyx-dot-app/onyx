"use client";

import { useState, type ReactNode } from "react";
import { Button, InputTypeIn, Modal, Text, Tooltip } from "@opal/components";
import { useTranslations } from "next-intl";
import type { RichStr } from "@opal/types";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";
import PolicyToggle from "@/sections/actions/PolicyToggle";
import type { ActionPolicy } from "@/app/craft/v1/apps/registry";

export interface ActionPolicyRow {
  id: string;
  name: string;
  description: string;
  fallbackPolicy: ActionPolicy;
  editable?: boolean;
  lockReason?: "workspace_disabled" | "workspace_managed" | null;
}
interface ActionPolicyRowsProps {
  items: ActionPolicyRow[];
  policies: Record<string, ActionPolicy>;
  onChange?: (policies: Record<string, ActionPolicy>) => void;
  disabled?: boolean;
}

export default function ActionPolicyRows({
  items,
  policies,
  onChange,
  disabled = false,
}: ActionPolicyRowsProps) {
  const t = useTranslations("craft.actionPolicies");
  const tPolicy = useTranslations("actions.policyToggle");
  return (
    <div className="flex flex-col gap-3">
      {items.map((item) => (
        <div
          key={item.id}
          className="flex flex-col items-start justify-between gap-3 sm:flex-row sm:items-center"
        >
          <div className="flex min-w-0 flex-1 flex-col">
            <Text font="main-ui-action" wordWrap="wrap-anywhere">
              {item.name}
            </Text>
            <Text
              font="secondary-body"
              color="text-03"
              wordWrap="wrap-anywhere"
            >
              {item.description}
            </Text>
            {item.lockReason && (
              <Text
                font="secondary-body"
                color="text-03"
                wordWrap="wrap-anywhere"
              >
                {t(item.lockReason)}
              </Text>
            )}
          </div>
          <Tooltip
            tooltip={
              item.lockReason === "workspace_disabled"
                ? t("workspaceDisabledTooltip")
                : undefined
            }
            side="top"
          >
            <div className="shrink-0">
              {onChange ? (
                <PolicyToggle
                  label={item.name}
                  disabled={disabled || item.editable === false}
                  value={
                    item.editable === false
                      ? item.fallbackPolicy
                      : (policies[item.id] ?? item.fallbackPolicy)
                  }
                  onChange={(value) =>
                    onChange({ ...policies, [item.id]: value })
                  }
                />
              ) : (
                <Text font="secondary-body">
                  {tPolicy(
                    item.fallbackPolicy === "ALWAYS"
                      ? "always.label"
                      : item.fallbackPolicy === "ASK"
                        ? "ask.label"
                        : "deny.label"
                  )}
                </Text>
              )}
            </div>
          </Tooltip>
        </div>
      ))}
    </div>
  );
}

interface ActionPoliciesModalProps extends Omit<
  ActionPolicyRowsProps,
  "disabled"
> {
  title: string | RichStr;
  description?: string | RichStr;
  onReset?: () => void;
  resetLabel?: string;
  children?: ReactNode;
  isDirty: boolean;
  saving?: boolean;
  onClose: () => void;
  onSave?: () => void;
  saveLabel?: string;
}

/** Owns dirty-dismiss confirmation; callers retain their policy drafts. */
export function ActionPoliciesModal({
  isDirty,
  saving = false,
  onClose,
  onSave,
  saveLabel,
  title,
  description,
  items,
  policies,
  onChange,
  onReset,
  resetLabel,
  children,
}: ActionPoliciesModalProps) {
  const t = useTranslations("craft.actionPolicies");
  const unsavedChanges = useUnsavedChangesGuard({ isDirty });
  function requestClose() {
    if (saving) return;
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
      <Modal.Content
        width={unsavedChanges.confirmationOpen ? "sm" : "lg"}
        height={unsavedChanges.confirmationOpen ? "fit" : "lg"}
        preventAccidentalClose={false}
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
            title={title}
            description={description}
            onClose={requestClose}
          ></Modal.Header>
          <Modal.Body>
            <ActionPolicyEditor
              items={items}
              policies={policies}
              onChange={onChange}
              onReset={onReset}
              resetLabel={resetLabel}
              disabled={saving}
            />
            {children}
          </Modal.Body>
          <Modal.Footer>
            <Button
              prominence="secondary"
              onClick={requestClose}
              disabled={saving}
            >
              {t(onSave ? "cancel" : "close")}
            </Button>
            {onSave && (
              <Button onClick={onSave} disabled={saving || !isDirty}>
                {saving ? t("saving") : (saveLabel ?? t("saveChanges"))}
              </Button>
            )}
          </Modal.Footer>
        </div>
      </Modal.Content>
    </Modal>
  );
}

interface ActionPolicyEditorProps extends ActionPolicyRowsProps {
  onReset?: () => void;
  resetLabel?: string;
}

/** Shared search, bulk edits, and rows for setup forms and permission modals. */
export function ActionPolicyEditor({
  items,
  policies,
  onChange,
  onReset,
  resetLabel,
  disabled = false,
}: ActionPolicyEditorProps) {
  const t = useTranslations("craft.actionPolicies");
  const tPolicy = useTranslations("actions.policyToggle");
  const [query, setQuery] = useState("");
  const search = query.trim().toLocaleLowerCase();
  const shownItems = items.filter(
    (item) =>
      !search ||
      `${item.name} ${item.description}`.toLocaleLowerCase().includes(search)
  );
  const editableItems = shownItems.filter((item) => item.editable !== false);
  const bulkOptions: { value: ActionPolicy; label: string }[] = [
    { value: "ALWAYS", label: tPolicy("always.label") },
    { value: "ASK", label: tPolicy("ask.label") },
    { value: "DENY", label: tPolicy("deny.label") },
  ];
  return (
    <div className="flex w-full flex-col gap-3">
      <div className="sticky top-0 z-10 flex flex-col gap-3 bg-background-tint-01 pb-3">
        <div className="w-full min-w-0">
          <InputTypeIn
            searchIcon
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("searchActions")}
            aria-label={t("searchActions")}
          />
        </div>
        {onChange && (
          <div className="flex w-full flex-wrap items-center justify-between gap-2">
            <Text font="secondary-body" color="text-03">
              {t("applyMatching", { count: editableItems.length })}
            </Text>
            <div className="ms-auto flex max-w-full flex-wrap justify-end gap-2">
              {bulkOptions.map((option) => (
                <Button
                  key={option.value}
                  size="sm"
                  prominence="secondary"
                  disabled={disabled || editableItems.length === 0}
                  onClick={() =>
                    onChange({
                      ...policies,
                      ...Object.fromEntries(
                        editableItems.map((item) => [item.id, option.value])
                      ),
                    })
                  }
                >
                  {option.label}
                </Button>
              ))}
              {onReset && (
                <Button
                  size="sm"
                  prominence="secondary"
                  disabled={disabled}
                  onClick={onReset}
                >
                  {resetLabel ?? t("resetAll")}
                </Button>
              )}
            </div>
          </div>
        )}
      </div>
      <div className="min-h-0">
        {shownItems.length ? (
          <ActionPolicyRows
            items={shownItems}
            policies={policies}
            onChange={onChange}
            disabled={disabled}
          />
        ) : (
          <Text font="secondary-body" color="text-03">
            {t(items.length ? "noMatchingActions" : "emptyActions")}
          </Text>
        )}
      </div>
    </div>
  );
}
