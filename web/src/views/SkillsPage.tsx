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
  useCreateModal,
} from "@opal/components";
import {
  IllustrationContent,
  SettingsLayouts,
  Toolbar,
  Section,
  toast,
} from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgBlocks,
  SvgEdit,
  SvgPlus,
  SvgUploadCloud,
  SvgUsers,
} from "@opal/icons";
import { usePluginBulkActions } from "@/sections/skills/usePluginBulkActions";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import AdminSkillsTable from "@/sections/skills/AdminSkillsTable";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import SkillReviewRequests from "@/sections/skills/SkillReviewRequests";
import SkillLimitUsersBanner from "@/sections/skills/SkillLimitUsersBanner";
import SkillPublishingCard from "@/sections/skills/SkillPublishingCard";
import type { CustomSkill } from "@/lib/skills/types";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { refreshSkillListsChecked } from "@/lib/skills/cache";
import { canManageSkill } from "@/lib/skills/sharing";
import { useSettings } from "@/lib/settings/hooks";
import { usePluginDelete, usePluginEnablement } from "@/lib/skills/hooks";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
import { adminSkillHref, newSkillHref } from "@/lib/customize/paths";

export default function AdminSkillsPage() {
  const t = useTranslations("skills");
  const bulkCopy = useTranslations("skills.bulk");
  const { isGlobalHolder: canManageOrgSkills } = usePermissionAuthority(
    Permission.MANAGE_PLUGINS
  );
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
  // Drop the skill now, so a failed refresh does not show it.
  const deletion = usePluginDelete({
    noun: "skill",
    onDeleted: async (deleted) => {
      await refresh(
        (current) =>
          current && {
            ...current,
            customs: current.customs.filter((skill) => skill.id !== deleted.id),
          },
        { revalidate: false }
      );
    },
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [groupFilter, setGroupFilter] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  async function deleteSkill() {
    if (!deleteTarget || !canManageSkill(deleteTarget)) return;
    if (await deletion.remove(deleteTarget)) deleteModal.toggle(false);
  }

  const items = useMemo<CustomSkill[]>(
    () =>
      (data?.customs ?? [])
        // Plugins have their own admin page.
        .filter(
          (skill): skill is CustomSkill =>
            skill.source === "custom" && skill.kind !== "plugin"
        )
        .sort((a, b) =>
          a.name.localeCompare(b.name, undefined, { sensitivity: "base" })
        ),
    [data]
  );
  const enablement = usePluginEnablement(items, refresh);

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

  const bulk = usePluginBulkActions({
    items: visibleItems,
    enablement,
    noun: "skill",
  });

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
        {bulk.failures}

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
                    readOnly={bulk.busy}
                    onChange={(event) => {
                      setSearchQuery(event.target.value);
                      bulk.reset();
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
                          disabled={bulk.busy}
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
                            bulk.reset();
                          }}
                        />,
                      ]
                    : []
                }
                actions={bulk.toolbarActions}
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
              <Section height="auto" alignItems="stretch">
                <AdminSkillsTable
                  skills={visibleItems}
                  bulk={bulk}
                  enablement={enablement}
                  onOpen={(skill) => navigation.go(adminSkillHref(skill.id))}
                  onShare={setShareTarget}
                  onDelete={(skill) => {
                    setDeleteTarget(skill);
                    deleteModal.toggle(true);
                  }}
                />
              </Section>
            )}
          </>
        )}
        {canManageOrgSkills && <SkillPublishingCard />}
      </SettingsLayouts.Body>

      {bulk.modals}

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

      <deleteModal.Provider>
        {deleteTarget && (
          <ConfirmEntityModal
            danger
            entityType={t("editor.deleteModal.entityType")}
            entityName={deleteTarget.name}
            additionalDetails={t("editor.delete.description")}
            actionButtonText={t(
              deletion.deleting
                ? "editor.deleteModal.pendingLabel"
                : "editor.deleteModal.label"
            )}
            onClose={() => {
              if (!deletion.deleting) deleteModal.toggle(false);
            }}
            onSubmit={() => void deleteSkill()}
          />
        )}
      </deleteModal.Provider>

      <SkillSwitchModal enablement={enablement} />
    </SettingsLayouts.Root>
  );
}
