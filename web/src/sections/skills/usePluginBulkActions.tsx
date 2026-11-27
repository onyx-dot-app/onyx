"use client";

import { useEffect, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dropdown,
  MessageCard,
  Text,
  type DropdownMenuRow,
} from "@opal/components";
import { ConfirmationModalLayout, Content, Section } from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
  SvgXCircle,
} from "@opal/icons";
import {
  isDisableTarget,
  usePluginBulkSelection,
  type PluginNoun,
  type PluginEnablement,
} from "@/lib/skills/hooks";
import type { CustomSkill } from "@/lib/skills/types";
import { skillIcon } from "@/sections/customize/skillIcon";
import BulkSkillSharingModal from "@/sections/modals/skills/BulkSkillSharingModal";

interface PluginBulkActionsOptions {
  items: readonly CustomSkill[];
  enablement: Pick<PluginEnablement, "isPending" | "enabledOf">;
  noun: PluginNoun;
}

export interface PluginBulkActions {
  selectedIds: ReadonlySet<string>;
  select: (ids: ReadonlySet<string>) => void;
  busy: boolean;
  /** Clears the selection and the failure report, as a filter change must. */
  reset: () => void;
  /** Opens the delete confirm for exactly these skills. */
  confirmDelete: (items: CustomSkill[]) => void;
  /** The count and bulk buttons for the toolbar, or nothing with no selection. */
  toolbarActions: ReactNode;
  /** The report of the skills the last bulk action could not change. */
  failures: ReactNode;
  modals: ReactNode;
}

/** The bulk toolbar actions, failure report and dialogs for an admin table
 * of skills or plugins. */
export function usePluginBulkActions({
  items,
  enablement,
  noun,
}: PluginBulkActionsOptions): PluginBulkActions {
  const bulkCopy = useTranslations("skills.bulk");
  const pluginNounCopy = useTranslations("plugins.bulk");
  // The strings that name the rows say "plugin" or "skill".
  const nounCopy = noun === "plugin" ? pluginNounCopy : bulkCopy;
  const {
    selectedIds,
    select,
    selectedItems,
    deleteTargets,
    toggleableItems,
    canShareSelected,
    busy,
    locked,
    deleteLocked,
    failures,
    failuresTitle,
    sharingOpen,
    setSharingOpen,
    deleteModal,
    confirmDelete,
    run,
    reset,
  } = usePluginBulkSelection({ items, enablement, noun });

  // A sync can remove every selected plugin; Share has nothing left to save.
  const nothingSelected = selectedItems.length === 0;
  useEffect(() => {
    if (nothingSelected) setSharingOpen(false);
  }, [nothingSelected, setSharingOpen]);

  const toggleActions: DropdownMenuRow[] = [];
  if (toggleableItems.some((item) => !item.enabled)) {
    toggleActions.push({
      kind: "action",
      id: "enable",
      icon: SvgCheckCircle,
      title: bulkCopy("enable"),
      disabled: locked,
      onSelect: () => void run("enable"),
    });
  }
  if (toggleableItems.some(isDisableTarget)) {
    toggleActions.push({
      kind: "action",
      id: "disable",
      icon: SvgXCircle,
      title: bulkCopy("disable"),
      disabled: locked,
      onSelect: () => void run("disable"),
    });
  }

  const toolbarActions = selectedItems.length > 0 && (
    <>
      <Text as="p" font="secondary-body" color="text-03">
        {bulkCopy("selected", { count: selectedItems.length })}
      </Text>
      <Button
        prominence="secondary"
        icon={SvgShare}
        disabled={locked || !canShareSelected}
        onClick={() => setSharingOpen(true)}
      >
        {bulkCopy("share")}
      </Button>
      <Dropdown align="end" disabled={locked}>
        <Dropdown.Trigger asChild>
          <Button
            prominence="tertiary"
            icon={SvgMoreHorizontal}
            aria-label={bulkCopy("moreActions")}
            tooltip={bulkCopy("moreActions")}
            disabled={locked}
          />
        </Dropdown.Trigger>
        <Dropdown.Data
          label={bulkCopy("moreActions")}
          items={[
            { kind: "group", items: toggleActions },
            {
              kind: "group",
              items: [
                {
                  kind: "action",
                  id: "delete",
                  icon: SvgTrash,
                  title: bulkCopy("delete"),
                  danger: true,
                  disabled: selectedItems.some((item) => !item.can_delete),
                  onSelect: () => confirmDelete(selectedItems),
                },
              ],
            },
          ]}
        />
      </Dropdown>
    </>
  );

  const failureReport = failures.length > 0 && (
    <MessageCard
      variant="error"
      title={failuresTitle}
      description={failures
        .map((failure) => `${failure.name}: ${failure.detail}`)
        .join("\n")}
    />
  );

  const singleDeleteTarget =
    deleteTargets.length === 1 ? deleteTargets[0] : undefined;

  const modals = (
    <>
      <BulkSkillSharingModal
        // A new target set starts a new draft: a staged publish must not carry
        // over to other skills.
        key={selectedItems
          .map((item) => item.id)
          .sort()
          .join(",")}
        nounCopy={nounCopy}
        items={selectedItems}
        open={sharingOpen}
        saving={busy}
        onClose={() => setSharingOpen(false)}
        onSave={(sharing) => run("share", sharing)}
      />
      <deleteModal.Provider>
        <ConfirmationModalLayout
          icon={SvgAlertTriangle}
          title={
            singleDeleteTarget
              ? nounCopy("deleteOneTitle", { name: singleDeleteTarget.name })
              : nounCopy("deleteTitle", { count: deleteTargets.length })
          }
          description={
            singleDeleteTarget
              ? nounCopy("deleteOneDescription")
              : nounCopy("deleteDescription", { count: deleteTargets.length })
          }
          onClose={() => {
            if (!busy) deleteModal.toggle(false);
          }}
          submit={
            <Button
              variant="danger"
              disabled={deleteLocked}
              onClick={() => void run("delete")}
            >
              {bulkCopy("delete")}
            </Button>
          }
        >
          <Section
            role="list"
            height="auto"
            alignItems="stretch"
            gap={2}
            className="max-h-60 overflow-y-auto"
          >
            {deleteTargets.map((item) => (
              <Section
                key={item.id}
                role="listitem"
                height="auto"
                alignItems="stretch"
              >
                <Content
                  font="main-ui-body"
                  icon={skillIcon(item)}
                  title={item.name}
                />
              </Section>
            ))}
          </Section>
        </ConfirmationModalLayout>
      </deleteModal.Provider>
    </>
  );

  return {
    selectedIds,
    select,
    busy,
    reset,
    confirmDelete,
    toolbarActions,
    failures: failureReport,
    modals,
  };
}
