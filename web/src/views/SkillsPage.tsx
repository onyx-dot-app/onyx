"use client";

import { useNavigation, useSearchParams } from "@opal/navigation";
import { IconLoader } from "@opal/loaders";
import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  Button,
  Collapsible,
  InputTypeIn,
  InputCheckbox,
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
  CardGrid,
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
import TextSeparator from "@/refresh-components/TextSeparator";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import SkillCard, {
  type CustomSkillCardItem,
  type SkillCardItem,
} from "@/sections/cards/SkillCard";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import SkillPreviewModal from "@/sections/modals/SkillPreviewModal";
import SkillReviewRequests from "@/sections/skills/SkillReviewRequests";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import {
  deleteUserSkill,
  bulkUpdateSkills,
  type SkillShareUpdatePayload,
  isSkillNameConflict,
  setSkillEnabled,
} from "@/lib/skills/api";
import { useSettings } from "@/lib/settings/hooks";

interface SkillsPageProps {
  admin?: boolean;
}

export default function SkillsPage({ admin = false }: SkillsPageProps) {
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
  const externalAppIdParam = useSearchParams().get("externalAppId");
  const focusedExternalAppId =
    externalAppIdParam !== null && /^\d+$/.test(externalAppIdParam)
      ? Number(externalAppIdParam)
      : null;
  const { data, error, isLoading, refresh } = useUserSkills();
  // Revalidation after a successful change is best effort.
  function revalidateSkills() {
    return refresh().catch(() => undefined);
  }
  const { mutate } = useSWRConfig();
  const [deleteTarget, setDeleteTarget] = useState<CustomSkillCardItem | null>(
    null
  );
  const deleteModal = useCreateModal();
  const [deleting, setDeleting] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [builtinsOpen, setBuiltinsOpen] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const githubImportModal = useCreateModal();
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [skillDialog, setSkillDialog] = useState<{
    item: SkillCardItem;
    tab: "details" | "sharing";
  } | null>(null);
  const previewTarget = skillDialog?.item ?? null;
  const [pendingSkillIds, setPendingSkillIds] = useState<Set<string>>(
    new Set()
  );
  const [optimisticEnabledById, setOptimisticEnabledById] = useState<
    Map<string, boolean>
  >(new Map());
  const [pendingSwitchTarget, setPendingSwitchTarget] =
    useState<SkillCardItem | null>(null);
  const switchModal = useCreateModal();
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  async function deleteSkill() {
    if (
      !deleteTarget ||
      deleting ||
      (deleteTarget.skill.user_permission !== "OWNER" &&
        deleteTarget.skill.user_permission !== "EDITOR")
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
      if (deleteTarget.external_app) {
        void mutate(SWR_KEYS.buildExternalAppsAdmin).catch((error: unknown) => {
          console.error(
            "Failed to refresh external app after skill deletion",
            error
          );
        });
      }
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

  function handleEdit(item: CustomSkillCardItem) {
    navigation.go(`/craft/v1/skills/edit/${item.id}`);
  }

  async function updateSkillEnabled(
    item: SkillCardItem,
    enabled: boolean,
    replaceConflict = false
  ) {
    if (
      enabled &&
      !replaceConflict &&
      items.some(
        (candidate) =>
          candidate.id !== item.id &&
          candidate.name === item.name &&
          candidate.enabled
      )
    ) {
      setPendingSwitchTarget(item);
      switchModal.toggle(true);
      return;
    }

    const affectedItems =
      enabled && replaceConflict
        ? items.filter(
            (candidate) =>
              candidate.id === item.id ||
              (candidate.name === item.name && candidate.enabled)
          )
        : [item];
    const affectedIds = new Set(affectedItems.map(({ id }) => id));
    setPendingSkillIds((current) => {
      const next = new Set(current);
      affectedIds.forEach((id) => next.add(id));
      return next;
    });
    setOptimisticEnabledById((current) => {
      const next = new Map(current);
      if (enabled) {
        affectedItems.forEach((candidate) =>
          next.set(candidate.id, candidate.id === item.id)
        );
      } else {
        next.set(item.id, false);
      }
      return next;
    });
    try {
      const updatedSkill = await setSkillEnabled(
        item.id,
        enabled,
        replaceConflict
      );
      if (replaceConflict) switchModal.toggle(false);
      await refresh(
        (current) => {
          if (!current) return current;
          return {
            ...current,
            builtins: current.builtins.map((skill) => {
              if (
                updatedSkill.source === "builtin" &&
                skill.id === updatedSkill.id
              ) {
                return updatedSkill;
              }
              if (enabled && skill.name === updatedSkill.name) {
                return { ...skill, enabled: false };
              }
              return skill;
            }),
            customs: current.customs.map((skill) => {
              if (
                updatedSkill.source === "custom" &&
                skill.id === updatedSkill.id
              ) {
                return updatedSkill;
              }
              if (enabled && skill.name === updatedSkill.name) {
                return { ...skill, enabled: false };
              }
              return skill;
            }),
          };
        },
        { revalidate: false }
      );
      void refresh().catch(() => {
        toast.error(t("page.toasts.refreshFailed", { name: item.name }));
      });
    } catch (error) {
      if (enabled && !replaceConflict && isSkillNameConflict(error)) {
        setPendingSwitchTarget(item);
        switchModal.toggle(true);
        return;
      }
      toast.error(
        error instanceof Error
          ? error.message
          : t(
              enabled
                ? "page.toasts.enableFailed"
                : "page.toasts.disableFailed",
              { name: item.name }
            )
      );
    } finally {
      setOptimisticEnabledById((current) => {
        const next = new Map(current);
        affectedIds.forEach((id) => next.delete(id));
        return next;
      });
      setPendingSkillIds((current) => {
        const next = new Set(current);
        affectedIds.forEach((id) => next.delete(id));
        return next;
      });
    }
  }

  const items = useMemo<SkillCardItem[]>(() => {
    if (!data) return [];
    const builtinItems: SkillCardItem[] = data.builtins
      .filter(
        (b): b is BuiltinSkill =>
          !admin && b.source === "builtin" && b.is_available !== null
      )
      .map((b) => ({
        id: b.id,
        name: b.name,
        description: b.description,
        source: "builtin",
        enabled: optimisticEnabledById.get(b.id) ?? b.enabled,
        can_toggle: b.can_toggle,
        is_available: b.is_available,
        unavailable_reason: b.unavailable_reason,
        external_app: b.external_app,
      }));
    const customItems: SkillCardItem[] = data.customs
      .filter((c): c is CustomSkill => c.source === "custom")
      .map((c) => ({
        id: c.id,
        name: c.name,
        description: c.description,
        source: "custom",
        skill: c,
        author_email: c.author_email,
        is_personal: c.is_personal && c.user_permission === "OWNER",
        enabled: optimisticEnabledById.get(c.id) ?? c.enabled,
        can_toggle: c.can_toggle,
        external_app: c.external_app,
      }));
    const groupRank = (item: SkillCardItem): number => {
      switch (item.source) {
        case "builtin":
          return 0;
        case "custom":
          return item.is_personal ? 2 : 1;
      }
    };
    return [...builtinItems, ...customItems].sort(
      (a, b) =>
        groupRank(a) - groupRank(b) ||
        a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    );
  }, [data, optimisticEnabledById, admin]);

  const focusedAppName = useMemo(() => {
    if (focusedExternalAppId === null) return null;
    for (const item of items) {
      if (item.external_app?.external_app_id === focusedExternalAppId) {
        return item.external_app.name;
      }
    }
    return null;
  }, [focusedExternalAppId, items]);

  const enabledItemByName = useMemo(
    () =>
      new Map(
        items
          .filter((item) => item.enabled)
          .map((item) => [item.name, item] as const)
      ),
    [items]
  );

  // The groups of the summaries the caller may see.
  const groupOptions = useMemo(() => {
    const names = new Map<number, string>();
    for (const item of items) {
      if (item.source !== "custom") continue;
      for (const summary of item.skill.group_summaries) {
        names.set(summary.group_id, summary.group_name);
      }
    }
    return Array.from(names, ([id, name]) => ({ id, name })).sort((a, b) =>
      a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
    );
  }, [items]);
  // A group that left every summary after a refresh stops filtering.
  const activeGroupId =
    groupOptions.find((group) => String(group.id) === groupFilter)?.id ?? null;

  const visibleItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return items.filter(
      (item) =>
        (focusedAppName === null ||
          item.external_app?.external_app_id === focusedExternalAppId) &&
        (activeGroupId === null ||
          (item.source === "custom" &&
            item.skill.group_summaries.some(
              (summary) => summary.group_id === activeGroupId
            ))) &&
        (!q ||
          item.name.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q))
    );
  }, [activeGroupId, focusedAppName, focusedExternalAppId, items, searchQuery]);

  const selectableItems = visibleItems.filter(
    (item): item is CustomSkillCardItem => item.source === "custom"
  );
  const visibleBuiltins = visibleItems.filter(
    (item): item is Extract<SkillCardItem, { source: "builtin" }> =>
      item.source === "builtin"
  );
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
        item.skill.user_permission === "OWNER" ||
        item.skill.user_permission === "EDITOR"
    );
  const toggleableItems = selectedItems.filter((item) => item.can_toggle);
  // A card toggle still in flight must settle before a bulk action may race it.
  const bulkLocked =
    bulkBusy || selectedItems.some((item) => pendingSkillIds.has(item.id));

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
      await Promise.all([
        revalidateSkills(),
        mutate(SWR_KEYS.buildExternalAppsAdmin),
      ]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : bulkCopy("failed"));
    } finally {
      setBulkBusy(false);
    }
  }

  const switchPending =
    pendingSwitchTarget !== null && pendingSkillIds.has(pendingSwitchTarget.id);
  const editablePreview =
    previewTarget?.source === "custom" &&
    (previewTarget.skill.user_permission === "OWNER" ||
      previewTarget.skill.user_permission === "EDITOR")
      ? previewTarget
      : null;
  const previewUnavailableReason =
    previewTarget?.source === "builtin" && !previewTarget.is_available
      ? (previewTarget.unavailable_reason ??
        t("page.preview.unavailableFallback"))
      : null;

  return (
    <SettingsLayouts.Root data-testid="SkillsPage/container">
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title={t("page.header.title")}
        description={
          admin ? bulkCopy("adminDescription") : t("page.header.description")
        }
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
                  onSelect: () => navigation.go("/craft/v1/skills/new"),
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
      >
        <Section
          flexDirection="row"
          wrap
          gap={2}
          height="auto"
          alignItems="stretch"
        >
          <Section
            height="auto"
            alignItems="stretch"
            className="min-w-0 grow-[3] basis-64"
          >
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
          </Section>
          {groupOptions.length > 0 && (
            <Section
              height="auto"
              alignItems="stretch"
              className="min-w-0 grow basis-48"
            >
              <InputSingleSelect
                search
                placeholder={t("groups.filter.placeholder")}
                value={activeGroupId === null ? "all" : String(activeGroupId)}
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
              />
            </Section>
          )}
        </Section>
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        {canManageOrgSkills && (admin || !isAdmin) && (
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

        {focusedAppName && (
          <MessageCard
            variant="info"
            title={t("page.focusedApp.title", { appName: focusedAppName })}
            description={t("page.focusedApp.description", {
              appName: focusedAppName,
            })}
            rightChildren={
              <Button
                prominence="secondary"
                {...navigation.linkTo("/craft/v1/skills")}
              >
                {t("page.focusedApp.showAll.label")}
              </Button>
            }
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
                  <>
                    <Section height="auto" gap={2} alignItems="stretch">
                      <Section
                        role="group"
                        aria-label={t("page.browse.title")}
                        flexDirection="row"
                        justifyContent="between"
                        height={2.25}
                        gap={2}
                      >
                        <Section
                          flexDirection="row"
                          justifyContent="start"
                          width="auto"
                          height="auto"
                          gap={2}
                          className="shrink-0"
                        >
                          <InputCheckbox
                            aria-label={bulkCopy("selectAll")}
                            checked={
                              selectedItems.length === selectableItems.length
                            }
                            indeterminate={
                              selectedItems.length > 0 &&
                              selectedItems.length < selectableItems.length
                            }
                            disabled={bulkBusy}
                            onCheckedChange={(checked) =>
                              setSelectedIds(
                                new Set(
                                  checked
                                    ? selectableItems.map((item) => item.id)
                                    : []
                                )
                              )
                            }
                          />
                          <Text font="secondary-body" color="text-03">
                            {selectedItems.length > 0
                              ? bulkCopy("selected", {
                                  count: selectedItems.length,
                                })
                              : t("page.browse.title")}
                          </Text>
                        </Section>
                        {selectedItems.length > 0 && (
                          <Section
                            flexDirection="row"
                            width="auto"
                            height="full"
                            gap={2}
                            justifyContent="start"
                            className="min-w-0 overflow-x-auto"
                          >
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
                                          !canManageSelected ||
                                          (!isAdmin &&
                                            selectedItems.some(
                                              (item) =>
                                                item.skill
                                                  .installation_policy ===
                                                "REQUIRED"
                                            )) ||
                                          (!canManageOrgSkills &&
                                            selectedItems.some(
                                              (item) =>
                                                item.skill.public_permission !==
                                                null
                                            )),
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
                          </Section>
                        )}
                      </Section>
                      <CardGrid>
                        {selectableItems.map((item) => (
                          <SkillCard
                            key={item.id}
                            selection={{
                              checked: selectedIds.has(item.id),
                              disabled: bulkBusy,
                              onCheckedChange: (checked) =>
                                setSelectedIds((current) => {
                                  const next = new Set(current);
                                  if (checked) next.add(item.id);
                                  else next.delete(item.id);
                                  return next;
                                }),
                            }}
                            item={item}
                            hasEnabledNameConflict={
                              !item.enabled && enabledItemByName.has(item.name)
                            }
                            onEdit={handleEdit}
                            onShare={(skill) =>
                              setSkillDialog({ item: skill, tab: "sharing" })
                            }
                            onDelete={(skill) => {
                              setDeleteTarget(skill);
                              deleteModal.toggle(true);
                            }}
                            onClick={(skill) =>
                              setSkillDialog({ item: skill, tab: "details" })
                            }
                            onEnabledChange={(skill, enabled) =>
                              void updateSkillEnabled(skill, enabled)
                            }
                            enablementPending={
                              bulkBusy || pendingSkillIds.has(item.id)
                            }
                          />
                        ))}
                      </CardGrid>
                    </Section>
                    <TextSeparator
                      count={selectableItems.length}
                      text={t("page.countSeparator.label", {
                        count: selectableItems.length,
                      })}
                    />
                  </>
                ) : !searchQuery.trim() ? (
                  <IllustrationContent
                    illustration={SvgNoResult}
                    title={t("page.empty.noSkills.title")}
                    description={t("page.empty.noSkills.description")}
                  />
                ) : null}
                {visibleBuiltins.length > 0 && (
                  <Collapsible
                    title={t("page.builtins.title", {
                      count: visibleBuiltins.length,
                    })}
                    open={
                      builtinsOpen ||
                      (searchQuery.trim() !== "" && visibleBuiltins.length > 0)
                    }
                    onOpenChange={setBuiltinsOpen}
                  >
                    <CardGrid>
                      {visibleBuiltins.map((item) => (
                        <SkillCard
                          key={item.id}
                          item={item}
                          onClick={(skill) =>
                            setSkillDialog({ item: skill, tab: "details" })
                          }
                        />
                      ))}
                    </CardGrid>
                  </Collapsible>
                )}
              </>
            )}
          </>
        )}
      </SettingsLayouts.Body>

      <BulkSkillSharingModal
        count={selectedItems.length}
        canChangeOrgAccess={
          selectedItems.every((item) => item.skill.external_app === null) &&
          (isAdmin ||
            selectedItems.every(
              (item) => item.skill.user_permission === "OWNER"
            ))
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

      {editablePreview && (
        <ShareSkillModal
          mode="edit"
          skillId={editablePreview.id}
          initialTab={skillDialog?.tab ?? "details"}
          fallbackTitle={editablePreview.name}
          open
          onClose={() => setSkillDialog(null)}
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
          navigation.go(`/craft/v1/skills/new?draft=${draftId}`);
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

      <SkillPreviewModal
        open={previewTarget !== null && editablePreview === null}
        skillId={previewTarget?.id ?? null}
        fallbackTitle={previewTarget?.name}
        unavailableReason={previewUnavailableReason}
        onClose={() => setSkillDialog(null)}
      />

      <switchModal.Provider>
        {pendingSwitchTarget && (
          <ConfirmationModalLayout
            icon={SvgAlertTriangle}
            title={t("page.switchModal.title", {
              name: pendingSwitchTarget.name,
            })}
            description={t("page.switchModal.description", {
              name: pendingSwitchTarget.name,
            })}
            onClose={
              switchPending ? undefined : () => switchModal.toggle(false)
            }
            submit={
              <Button
                disabled={switchPending}
                onClick={() => {
                  const target = pendingSwitchTarget;
                  void updateSkillEnabled(target, true, true);
                }}
              >
                {switchPending
                  ? t("page.switchModal.submit.pendingLabel")
                  : t("page.switchModal.submit.label")}
              </Button>
            }
          >
            {t("page.switchModal.body")}
          </ConfirmationModalLayout>
        )}
      </switchModal.Provider>
    </SettingsLayouts.Root>
  );
}
