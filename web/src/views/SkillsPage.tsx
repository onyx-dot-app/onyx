"use client";

import { useNavigation } from "@opal/navigation";
import { IconLoader } from "@opal/loaders";
import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import {
  Button,
  InputTypeIn,
  InputSingleSelect,
  MessageCard,
  Dropdown,
  type DropdownMenuRow,
  Text,
  useCreateModal,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  IllustrationContent,
  SettingsLayouts,
  Toolbar,
  Content,
  Section,
  toast,
} from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgAlertTriangle,
  SvgBlocks,
  SvgCheckCircle,
  SvgEdit,
  SvgMoreHorizontal,
  SvgPlus,
  SvgShare,
  SvgTrash,
  SvgUploadCloud,
  SvgUsers,
  SvgXCircle,
} from "@opal/icons";
import { SvgGitHub } from "@opal/logos";
import BulkSkillSharingModal from "@/sections/modals/skills/BulkSkillSharingModal";
import { useUser } from "@/providers/UserProvider";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import AdminSkillsTable from "@/sections/skills/AdminSkillsTable";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import SkillReviewRequests from "@/sections/skills/SkillReviewRequests";
import SkillLimitUsersBanner from "@/sections/skills/SkillLimitUsersBanner";
import SkillPublishingCard from "@/sections/skills/SkillPublishingCard";
import type { CustomSkill } from "@/lib/skills/types";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { refreshSkillListsChecked } from "@/lib/skills/cache";
import {
  deleteUserSkill,
  bulkUpdateSkills,
  type SkillShareUpdatePayload,
} from "@/lib/skills/api";
import { useSettings } from "@/lib/settings/hooks";
import { useSkillEnablement } from "@/lib/skills/hooks";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
import {
  adminSkillHref,
  newSkillHref,
  pluginHref,
} from "@/lib/customize/paths";

export default function AdminSkillsPage() {
  const t = useTranslations("skills");
  const bulkCopy = useTranslations("skills.bulk");
  const { isAdmin } = useUser();
  const { isGlobalHolder: canManageOrgSkills } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkSharingOpen, setBulkSharingOpen] = useState(false);
  const bulkDeleteModal = useCreateModal();
  const [bulkFailures, setBulkFailures] = useState<
    { name: string; detail: string }[]
  >([]);
  const { appName } = useSettings();
  const navigation = useNavigation();
  const { data, error, isLoading, refresh } = useUserSkills();
  const { mutate, cache } = useSWRConfig();
  function revalidateSkills() {
    return refreshSkillListsChecked(mutate, cache).then((ok) => {
      if (!ok) toast.error(t("page.toasts.listRefreshFailed"));
    });
  }
  const [deleteTarget, setDeleteTarget] = useState<CustomSkill | null>(null);
  const deleteModal = useCreateModal();
  const [deleting, setDeleting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const githubImportModal = useCreateModal();
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  async function deleteSkill() {
    if (
      !deleteTarget ||
      deleting ||
      (deleteTarget.user_permission !== "OWNER" &&
        deleteTarget.user_permission !== "EDITOR")
    )
      return;
    setDeleting(true);
    try {
      await deleteUserSkill(deleteTarget.id);
      await refresh(
        (current) =>
          current && {
            ...current,
            customs: current.customs.filter(
              (skill) => skill.id !== deleteTarget.id
            ),
          },
        { revalidate: false }
      );
      void revalidateSkills();
      deleteModal.toggle(false);
      toast.success(t("editor.toasts.deleted", { name: deleteTarget.name }));
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("editor.toasts.deleteFailed")
      );
    } finally {
      setDeleting(false);
    }
  }

  const loadedItems = useMemo<CustomSkill[]>(
    () =>
      (data?.customs ?? [])
        .filter((skill): skill is CustomSkill => skill.source === "custom")
        .sort((a, b) =>
          a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
        ),
    [data]
  );
  const enablement = useSkillEnablement(loadedItems, refresh);
  const items = loadedItems.map((item) => ({
    ...item,
    enabled: enablement.enabledOf(item),
  }));

  // The groups of the summaries the caller may see.
  const groupOptions = useMemo(() => {
    const names = new Map<number, string>();
    for (const item of items) {
      for (const summary of item.group_summaries) {
        names.set(summary.group_id, summary.group_name);
      }
    }
    return Array.from(names, ([id, name]) => ({ id, name })).sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    );
  }, [items]);
  const activeGroupId =
    groupOptions.find((group) => String(group.id) === groupFilter)?.id ?? null;
  // A group that left every summary after a refresh clears the filter, so it
  // does not come back on when the group returns.
  if (groupFilter !== "" && activeGroupId === null) setGroupFilter("");

  const organizationLibrary = t("adminTable.organizationLibrary");
  const visibleItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return items.filter(
      (item) =>
        (activeGroupId === null ||
          item.group_summaries.some(
            (summary) => summary.group_id === activeGroupId
          )) &&
        (!q ||
          [
            item.name,
            item.description,
            item.owner?.email ?? "",
            item.published_version_number !== null ? organizationLibrary : "",
            ...item.group_summaries.map((summary) => summary.group_name),
          ].some((field) => field.toLowerCase().includes(q)))
    );
  }, [activeGroupId, items, searchQuery, organizationLibrary]);

  const selectableItems = visibleItems;
  const selectedItems = selectableItems.filter((item) =>
    selectedIds.has(item.id)
  );
  // The skills the bulk-delete confirm lists. Snapshotted on open: the
  // selection clears when the delete lands, while the card still fades out.
  const [bulkDeleteTargets, setBulkDeleteTargets] = useState(selectedItems);
  const canManageSelected =
    selectedItems.length > 0 &&
    selectedItems.every(
      (item) =>
        item.user_permission === "OWNER" || item.user_permission === "EDITOR"
    );
  const toggleableItems = selectedItems.filter((item) => item.can_toggle);
  // A card toggle still in flight must settle before a bulk action may race it.
  const bulkLocked =
    bulkBusy || selectedItems.some((item) => enablement.isPending(item.id));

  const bulkToggleActions: DropdownMenuRow[] = [];
  if (selectedItems.some((item) => !item.enabled)) {
    bulkToggleActions.push({
      kind: "action",
      id: "enable",
      icon: SvgCheckCircle,
      title: bulkCopy("enable"),
      disabled: bulkLocked || toggleableItems.length === 0,
      onSelect: () => void runBulk("enable"),
    });
  }
  if (selectedItems.some((item) => item.enabled)) {
    bulkToggleActions.push({
      kind: "action",
      id: "disable",
      icon: SvgXCircle,
      title: bulkCopy("disable"),
      disabled: bulkLocked || toggleableItems.length === 0,
      onSelect: () => void runBulk("disable"),
    });
  }

  async function runBulk(
    action: "share" | "enable" | "disable" | "delete",
    sharing?: SkillShareUpdatePayload
  ) {
    const pool = action === "delete" ? bulkDeleteTargets : selectedItems;
    if (bulkLocked || pool.length === 0) return;
    setBulkBusy(true);
    setBulkFailures([]);
    try {
      // Delete acts on exactly the skills its confirm listed.
      const targets =
        action === "enable" || action === "disable"
          ? toggleableItems
          : action === "delete"
            ? bulkDeleteTargets
            : selectedItems;
      const skill_ids = targets.map((item) => item.id);
      const result = await bulkUpdateSkills(
        action === "share"
          ? { action, skill_ids, sharing: sharing ?? {} }
          : { action, skill_ids }
      );
      setSelectedIds(new Set(result.failed.map((failure) => failure.skill_id)));
      // Names come from the request targets: a skill deleted elsewhere in the
      // meantime is gone from the refreshed list but must still be reported.
      setBulkFailures(
        result.failed.map((failure) => ({
          name:
            targets.find((item) => item.id === failure.skill_id)?.name ??
            failure.skill_id,
          detail: failure.detail,
        }))
      );
      if (result.succeeded.length)
        toast.success(bulkCopy("updated", { count: result.succeeded.length }));
      setBulkSharingOpen(false);
      bulkDeleteModal.toggle(false);
      await revalidateSkills();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : bulkCopy("failed"));
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <SettingsLayouts.Root width="lg" data-testid="SkillsPage/container">
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title={t("page.header.title")}
        description={bulkCopy("adminDescription")}
        actions={[
          <Dropdown
            key="primary"
            open={createMenuOpen}
            onOpenChange={setCreateMenuOpen}
          >
            <Dropdown.Trigger asChild>
              <Button icon={SvgPlus}>
                {t("page.createMenu.trigger.label")}
              </Button>
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("page.createMenu.trigger.label")}
              items={[
                {
                  kind: "action",
                  id: "scratch",
                  icon: SvgEdit,
                  title: t("page.createMenu.scratch.title"),
                  description: t("page.createMenu.scratch.description", {
                    appName,
                  }),
                  onSelect: () => navigation.go(newSkillHref()),
                },
                {
                  kind: "action",
                  id: "upload",
                  icon: SvgUploadCloud,
                  title: t("page.createMenu.upload.title"),
                  description: t("page.createMenu.upload.description"),
                  onSelect: () => setCreateOpen(true),
                },
                {
                  kind: "action",
                  id: "github",
                  icon: SvgGitHub,
                  title: t("page.createMenu.github.title"),
                  description: t("page.createMenu.github.description"),
                  onSelect: () => githubImportModal.toggle(true),
                },
              ]}
            />
          </Dropdown>,
        ]}
      />

      <SettingsLayouts.Body>
        {canManageOrgSkills && <SkillLimitUsersBanner />}
        {canManageOrgSkills && (
          <SkillReviewRequests onReviewed={() => void revalidateSkills()} />
        )}
        {bulkFailures.length > 0 && (
          <MessageCard
            variant="error"
            title={bulkCopy("partialFailure", { count: bulkFailures.length })}
            description={bulkFailures
              .map((failure) => `${failure.name}: ${failure.detail}`)
              .join("\n")}
          />
        )}

        {isLoading && <IconLoader />}

        {error && !isLoading && (
          <MessageCard
            variant="error"
            title={t("page.loadError.title")}
            description={t("page.loadError.description")}
          />
        )}

        {!isLoading && !error && (
          <>
            {items.length > 0 && (
              <Toolbar
                search={
                  <InputTypeIn
                    ref={searchInputRef}
                    placeholder={t("page.search.placeholder")}
                    value={searchQuery}
                    readOnly={bulkBusy}
                    onChange={(event) => {
                      setSearchQuery(event.target.value);
                      setSelectedIds(new Set());
                      setBulkFailures([]);
                    }}
                    icon="search"
                  />
                }
                filters={
                  groupOptions.length > 0
                    ? [
                        <InputSingleSelect
                          key="group"
                          search
                          placeholder={t("groups.filter.placeholder")}
                          value={
                            activeGroupId === null
                              ? "all"
                              : String(activeGroupId)
                          }
                          defaultOption="all"
                          disabled={bulkBusy}
                          options={[
                            {
                              value: "all",
                              title: t("groups.filter.all"),
                              icon: SvgUsers,
                            },
                            ...groupOptions.map((group) => ({
                              value: String(group.id),
                              title: group.name,
                              icon: SvgUsers,
                            })),
                          ]}
                          onValueChange={(value) => {
                            setGroupFilter(value);
                            setSelectedIds(new Set());
                            setBulkFailures([]);
                          }}
                        />,
                      ]
                    : []
                }
                actions={
                  selectedItems.length > 0 && (
                    <>
                      <Text as="p" font="secondary-body" color="text-03">
                        {bulkCopy("selected", { count: selectedItems.length })}
                      </Text>
                      <Button
                        prominence="secondary"
                        icon={SvgShare}
                        disabled={bulkLocked || !canManageSelected}
                        onClick={() => setBulkSharingOpen(true)}
                      >
                        {bulkCopy("share")}
                      </Button>
                      <Dropdown align="end" disabled={bulkLocked}>
                        <Dropdown.Trigger asChild>
                          <Button
                            prominence="tertiary"
                            icon={SvgMoreHorizontal}
                            aria-label={bulkCopy("moreActions")}
                            tooltip={bulkCopy("moreActions")}
                            disabled={bulkLocked}
                          />
                        </Dropdown.Trigger>
                        <Dropdown.Data
                          label={bulkCopy("moreActions")}
                          items={[
                            { kind: "group", items: bulkToggleActions },
                            {
                              kind: "group",
                              items: [
                                {
                                  kind: "action",
                                  id: "delete",
                                  icon: SvgTrash,
                                  title: bulkCopy("delete"),
                                  danger: true,
                                  disabled:
                                    selectedItems.length === 0 ||
                                    selectedItems.some(
                                      (item) => !item.can_delete
                                    ),
                                  onSelect: () => {
                                    setBulkDeleteTargets(selectedItems);
                                    bulkDeleteModal.toggle(true);
                                  },
                                },
                              ],
                            },
                          ]}
                        />
                      </Dropdown>
                    </>
                  )
                }
              />
            )}
            {visibleItems.length === 0 ? (
              <IllustrationContent
                illustration={SvgNoResult}
                title={
                  items.length === 0
                    ? t("page.empty.noSkills.title")
                    : t("page.empty.noMatches.title")
                }
                description={
                  items.length === 0
                    ? t("page.empty.noSkills.description")
                    : activeGroupId !== null
                      ? t("page.empty.noMatches.groupDescription")
                      : t("page.empty.noMatches.description")
                }
              />
            ) : (
              <>
                {selectableItems.length > 0 ? (
                  <Section height="auto" alignItems="stretch">
                    <AdminSkillsTable
                      skills={selectableItems}
                      selectedIds={selectedIds}
                      onSelectionChange={(ids) => setSelectedIds(new Set(ids))}
                      busy={bulkBusy}
                      isPending={enablement.isPending}
                      enabledOf={enablement.enabledOf}
                      onEnabledChange={(skill, enabled) =>
                        void enablement.setEnabled(skill, enabled)
                      }
                      onOpen={(skill) =>
                        navigation.go(
                          skill.kind === "plugin"
                            ? pluginHref(skill.id)
                            : adminSkillHref(skill.id)
                        )
                      }
                      onShare={setShareTarget}
                      onDelete={(skill) => {
                        setDeleteTarget(skill);
                        deleteModal.toggle(true);
                      }}
                    />
                  </Section>
                ) : !searchQuery.trim() ? (
                  <IllustrationContent
                    illustration={SvgNoResult}
                    title={t("page.empty.noSkills.title")}
                    description={t("page.empty.noSkills.description")}
                  />
                ) : null}
              </>
            )}
          </>
        )}
        {canManageOrgSkills && <SkillPublishingCard />}
      </SettingsLayouts.Body>

      <BulkSkillSharingModal
        count={selectedItems.length}
        canChangeOrgAccess={
          isAdmin ||
          selectedItems.every((item) => item.user_permission === "OWNER")
        }
        open={bulkSharingOpen}
        saving={bulkBusy}
        onClose={() => setBulkSharingOpen(false)}
        onSave={(sharing) => runBulk("share", sharing)}
      />
      <bulkDeleteModal.Provider>
        <ConfirmationModalLayout
          icon={SvgAlertTriangle}
          title={bulkCopy("deleteTitle", { count: bulkDeleteTargets.length })}
          description={bulkCopy("deleteDescription", {
            count: bulkDeleteTargets.length,
          })}
          onClose={() => {
            if (!bulkBusy) bulkDeleteModal.toggle(false);
          }}
          submit={
            <Button
              variant="danger"
              disabled={bulkBusy}
              onClick={() => void runBulk("delete")}
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
            {bulkDeleteTargets.map((item) => (
              <Section
                key={item.id}
                role="listitem"
                height="auto"
                alignItems="stretch"
              >
                <Content
                  font="main-ui-body"
                  icon={SvgBlocks}
                  title={item.name}
                />
              </Section>
            ))}
          </Section>
        </ConfirmationModalLayout>
      </bulkDeleteModal.Provider>

      {shareTarget && (
        <ShareSkillModal
          mode="edit"
          skillId={shareTarget.id}
          fallbackTitle={shareTarget.name}
          open
          onClose={() => setShareTarget(null)}
          onSaved={() => void revalidateSkills()}
        />
      )}

      <CreateSkillModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onImported={() => void revalidateSkills()}
        onContinue={(draft) => {
          const draftId = stageSkillCreationDraft(draft);
          setCreateOpen(false);
          navigation.go(newSkillHref(draftId));
        }}
      />

      <githubImportModal.Provider>
        <ImportSkillsFromGitHubModal
          open
          onClose={() => githubImportModal.toggle(false)}
          onImported={() => void revalidateSkills()}
        />
      </githubImportModal.Provider>

      <deleteModal.Provider>
        {deleteTarget && (
          <ConfirmEntityModal
            danger
            entityType={t("editor.deleteModal.entityType")}
            entityName={deleteTarget.name}
            additionalDetails={t("editor.delete.description")}
            actionButtonText={t(
              deleting
                ? "editor.deleteModal.pendingLabel"
                : "editor.deleteModal.label"
            )}
            onClose={() => {
              if (!deleting) deleteModal.toggle(false);
            }}
            onSubmit={() => void deleteSkill()}
          />
        )}
      </deleteModal.Provider>

      <SkillSwitchModal enablement={enablement} />
    </SettingsLayouts.Root>
  );
}
