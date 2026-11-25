"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  Dropdown,
  MessageCard,
  Text,
  useCreateModal,
  type DropdownMenuRow,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  Content,
  Section,
  toast,
} from "@opal/layouts";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
  SvgXCircle,
} from "@opal/icons";
import {
  bulkUpdateSkills,
  type SkillShareUpdatePayload,
} from "@/lib/skills/api";
import { refreshSkillListsChecked } from "@/lib/skills/cache";
import type { SkillEnablement } from "@/lib/skills/hooks";
import { canShareSkill } from "@/lib/skills/sharing";
import type { CustomSkill } from "@/lib/skills/types";
import { skillIcon } from "@/sections/customize/skillIcon";
import BulkSkillSharingModal, {
  type BulkSkillNoun,
} from "@/sections/modals/skills/BulkSkillSharingModal";

type BulkAction = "share" | "enable" | "disable" | "delete";

interface SkillBulkActionsOptions {
  items: readonly CustomSkill[];
  enablement: SkillEnablement;
  noun: BulkSkillNoun;
}

export interface SkillBulkActions {
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

/** Selection plus bulk share, enable, disable and delete for an admin table
 * of skills or plugins. */
export function useSkillBulkActions({
  items,
  enablement,
  noun,
}: SkillBulkActionsOptions): SkillBulkActions {
  const bulkCopy = useTranslations("skills.bulk");
  const pluginNounCopy = useTranslations("plugins.bulk");
  // The strings that name the rows say "plugin" or "skill".
  const nounCopy = noun === "plugin" ? pluginNounCopy : bulkCopy;
  const listCopy = useTranslations("skills");
  const { mutate, cache } = useSWRConfig();
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(
    new Set()
  );
  const [busy, setBusy] = useState(false);
  const [sharingOpen, setSharingOpen] = useState(false);
  const deleteModal = useCreateModal();
  const [failures, setFailures] = useState<{ name: string; detail: string }[]>(
    []
  );

  const selectedItems = items
    .filter((item) => selectedIds.has(item.id))
    .map((item) => ({ ...item, enabled: enablement.enabledOf(item) }));
  // The skills the delete confirm lists. Snapshotted on open: the selection
  // clears when the delete lands, while the card still fades out.
  const [deleteTargets, setDeleteTargets] = useState<CustomSkill[]>([]);
  const canShareSelected =
    selectedItems.length > 0 && selectedItems.every(canShareSkill);
  const toggleableItems = selectedItems.filter((item) => item.can_toggle);
  // A row toggle still in flight must settle before a bulk action may race it.
  const locked =
    busy || selectedItems.some((item) => enablement.isPending(item.id));

  async function run(action: BulkAction, sharing?: SkillShareUpdatePayload) {
    // Delete acts on exactly the skills its confirm listed.
    const targets =
      action === "delete"
        ? deleteTargets
        : action === "share"
          ? selectedItems
          : toggleableItems;
    if (locked || targets.length === 0) return;
    setBusy(true);
    setFailures([]);
    try {
      const skill_ids = targets.map((item) => item.id);
      const result = await bulkUpdateSkills(
        action === "share"
          ? { action, skill_ids, sharing: sharing ?? {} }
          : { action, skill_ids }
      );
      setSelectedIds(new Set(result.failed.map((failure) => failure.skill_id)));
      // Names come from the request targets: a skill deleted elsewhere in the
      // meantime is gone from the refreshed list but must still be reported.
      setFailures(
        result.failed.map((failure) => ({
          name:
            targets.find((item) => item.id === failure.skill_id)?.name ??
            failure.skill_id,
          detail: failure.detail,
        }))
      );
      if (result.succeeded.length)
        toast.success(nounCopy("updated", { count: result.succeeded.length }));
      setSharingOpen(false);
      deleteModal.toggle(false);
      if (!(await refreshSkillListsChecked(mutate, cache)))
        toast.error(listCopy("page.toasts.listRefreshFailed"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : nounCopy("failed"));
    } finally {
      setBusy(false);
    }
  }

  function confirmDelete(targets: CustomSkill[]) {
    setDeleteTargets(targets);
    deleteModal.toggle(true);
  }

  const toggleActions: DropdownMenuRow[] = [];
  if (selectedItems.some((item) => !item.enabled)) {
    toggleActions.push({
      kind: "action",
      id: "enable",
      icon: SvgCheckCircle,
      title: bulkCopy("enable"),
      disabled: locked || toggleableItems.length === 0,
      onSelect: () => void run("enable"),
    });
  }
  if (selectedItems.some((item) => item.enabled)) {
    toggleActions.push({
      kind: "action",
      id: "disable",
      icon: SvgXCircle,
      title: bulkCopy("disable"),
      disabled: locked || toggleableItems.length === 0,
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
      title={nounCopy("partialFailure", { count: failures.length })}
      description={failures
        .map((failure) => `${failure.name}: ${failure.detail}`)
        .join("\n")}
    />
  );

  const modals = (
    <>
      <BulkSkillSharingModal
        noun={noun}
        items={selectedItems}
        open={sharingOpen}
        saving={busy}
        onClose={() => setSharingOpen(false)}
        onSave={(sharing) => run("share", sharing)}
      />
      <deleteModal.Provider>
        <ConfirmationModalLayout
          icon={SvgAlertTriangle}
          title={nounCopy("deleteTitle", { count: deleteTargets.length })}
          description={nounCopy("deleteDescription", {
            count: deleteTargets.length,
          })}
          onClose={() => {
            if (!busy) deleteModal.toggle(false);
          }}
          submit={
            <Button
              variant="danger"
              disabled={busy}
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
    select: setSelectedIds,
    busy,
    reset: () => {
      setSelectedIds(new Set());
      setFailures([]);
    },
    confirmDelete,
    toolbarActions,
    failures: failureReport,
    modals,
  };
}
