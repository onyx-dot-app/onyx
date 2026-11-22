"use client";

import isEqual from "lodash/isEqual";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, InputSingleSelect, Modal, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type {
  TaskActionSettings,
  TaskIntegrationView,
} from "@/app/craft/v1/tasks/types";
import type { LinkValue } from "@/lib/integrations/types";
import PluginModalContent from "@/sections/plugins/PluginModalContent";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import { UnsavedChangesModalContent } from "@/sections/modals/UnsavedChangesModal";

function isLinkValue(value: string): value is LinkValue {
  return (
    value === "inherit" ||
    value === "allow" ||
    value === "ask" ||
    value === "blocked"
  );
}

interface TaskAppActionsModalProps {
  integration: TaskIntegrationView;
  settings: TaskActionSettings;
  onClose: () => void;
  onSave: (settings: TaskActionSettings) => void;
}

export default function TaskAppActionsModal({
  integration,
  settings: initialSettings,
  onClose,
  onSave,
}: TaskAppActionsModalProps) {
  const t = useTranslations("craft.actionPolicies");
  const [settings, setSettings] = useState(initialSettings);
  const isDirty = !isEqual(settings, initialSettings);
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
            title={t("appTitle", { name: integration.name })}
            description={t("taskModalDescription")}
            onClose={requestClose}
          />
          <Modal.Body>
            <Section height="auto" alignItems="stretch" gap={4}>
              {integration.actions.length === 0 && (
                <Text font="secondary-body" color="text-03">
                  {t("emptyActions")}
                </Text>
              )}
              {integration.actions.map((action) => (
                <Section
                  key={action.key}
                  height="auto"
                  flexDirection="row"
                  justifyContent="between"
                  gap={3}
                >
                  <Section
                    height="auto"
                    alignItems="start"
                    gap={0}
                    className="min-w-0 flex-1"
                  >
                    <Text font="main-ui-action" wordWrap="wrap-anywhere">
                      {action.display_name}
                    </Text>
                    {action.description && (
                      <Text
                        font="secondary-body"
                        color="text-03"
                        wordWrap="wrap-anywhere"
                      >
                        {action.description}
                      </Text>
                    )}
                  </Section>
                  <div className="w-56 shrink-0">
                    <InputSingleSelect
                      aria-label={t("actionSetting", {
                        action: action.display_name,
                      })}
                      placeholder={t("actionSetting", {
                        action: action.display_name,
                      })}
                      value={settings.actions[action.key] ?? settings.default}
                      options={[
                        {
                          value: "inherit",
                          title: t("value.inherit", {
                            policy: t(`value.${action.integration_policy}`),
                          }),
                        },
                        {
                          value: "allow",
                          title: t("value.allow"),
                          // The run keeps the integration policy.
                          disabled: action.locked,
                          tooltip: action.locked ? t("lockedAllow") : undefined,
                        },
                        { value: "ask", title: t("value.ask") },
                        { value: "blocked", title: t("value.blocked") },
                      ]}
                      onValueChange={(value) => {
                        if (!isLinkValue(value)) return;
                        setSettings((current) => ({
                          ...current,
                          actions: {
                            ...current.actions,
                            [action.key]: value,
                          },
                        }));
                      }}
                    />
                  </div>
                </Section>
              ))}
            </Section>
          </Modal.Body>
          <Modal.Footer>
            <Button prominence="secondary" onClick={requestClose}>
              {t("cancel")}
            </Button>
            <Button disabled={!isDirty} onClick={() => onSave(settings)}>
              {t("saveChanges")}
            </Button>
          </Modal.Footer>
        </div>
      </PluginModalContent>
    </Modal>
  );
}
