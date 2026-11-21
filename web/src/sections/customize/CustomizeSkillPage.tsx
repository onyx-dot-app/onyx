"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import useSWR, { useSWRConfig } from "swr";
import {
  Badge,
  Button,
  CopyButton,
  Dropdown,
  InputSwitch,
  MessageCard,
  useCreateModal,
  type DropdownMenuItem,
} from "@opal/components";
import { Section, toast } from "@opal/layouts";
import { IconLoader } from "@opal/loaders";
import { SvgEdit, SvgMoreHorizontal, SvgShare, SvgTrash } from "@opal/icons";
import { useNavigation, useSearchParams } from "@opal/navigation";
import useUserSkills from "@/hooks/useUserSkills";
import {
  adminSkillHref,
  customizeTabHref,
  pluginHref,
  skillHref,
} from "@/lib/customize/paths";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { deleteUserSkill } from "@/lib/skills/api";
import { refreshSkillLists } from "@/lib/skills/cache";
import { useRefreshSkillLists, useSkillEnablement } from "@/lib/skills/hooks";
import { canChangeOrganizationAccess } from "@/lib/skills/sharing";
import type { SkillEditableDetail, SkillPreview } from "@/lib/skills/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import CustomizeDetailLayout, {
  BackLink,
  DetailOverview,
  type DetailTab,
} from "@/sections/customize/CustomizeDetailLayout";
import { skillIcon } from "@/sections/customize/skillIcon";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import ShareSkillModal from "@/sections/modals/skills/ShareSkillModal";
import SkillSwitchModal from "@/sections/modals/skills/SkillSwitchModal";
import UnsavedChangesModal from "@/sections/modals/UnsavedChangesModal";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import SkillVersionsTab from "@/sections/modals/skills/SkillVersionsTab";
import SkillContentsTab from "@/sections/customize/SkillContentsTab";

const TABS = ["overview", "contents", "versions"] as const;

type SkillPageTab = (typeof TABS)[number];

function parseTab(value: string | null): SkillPageTab {
  return TABS.find((tab) => tab === value) ?? "overview";
}

interface CustomizeSkillPageProps {
  skillId: string;
  /** The list the back link returns to. */
  from?: "customize" | "admin";
}

/** One custom skill: Overview, Contents and Versions. Edit opens the editor
 * on the same route with `?edit=1`. */
export default function CustomizeSkillPage({
  skillId,
  from = "customize",
}: CustomizeSkillPageProps) {
  const t = useTranslations("customize.skillPage");
  const skillCopy = useTranslations("skills");
  const format = useFormatter();
  const navigation = useNavigation();
  const searchParams = useSearchParams();
  const { user } = useUser();
  const { mutate } = useSWRConfig();
  const { isGlobalHolder } = usePermissionAuthority(Permission.MANAGE_PLUGINS);
  const list = useUserSkills();
  const enablement = useSkillEnablement(list.data?.customs ?? [], list.refresh);
  const refreshLists = useRefreshSkillLists();
  const listed = list.data?.customs.find((item) => item.id === skillId);
  const isPlugin = listed?.kind === "plugin";
  const canEdit =
    !isPlugin &&
    (listed?.user_permission === "OWNER" ||
      listed?.user_permission === "EDITOR");
  const locked = listed?.content_locked === true;
  const canChangeContent = canEdit && !locked;
  const detail = useSWR<SkillEditableDetail>(
    canEdit ? SWR_KEYS.editableSkill(skillId) : null,
    errorHandlingFetcher
  );
  const preview = useSWR<SkillPreview>(
    listed && !isPlugin && !canEdit ? SWR_KEYS.userSkillPreview(skillId) : null,
    errorHandlingFetcher
  );
  useEffect(() => {
    if (isPlugin) navigation.go(pluginHref(skillId), { replace: true });
  }, [isPlugin, navigation, skillId]);
  const [sharing, setSharing] = useState(false);
  const [contentsDirty, setContentsDirty] = useState(false);
  const removeModal = useCreateModal();
  const [removing, setRemoving] = useState(false);

  const skill = detail.data ?? (canEdit ? undefined : listed);
  const instructions =
    detail.data?.instructions_markdown ?? preview.data?.instructions_markdown;
  const files = detail.data?.files ?? preview.data?.files ?? null;
  const editing = canChangeContent && searchParams.get("edit") === "1";
  const unsaved = useUnsavedChangesGuard({ isDirty: editing && contentsDirty });
  const tab = editing ? "contents" : parseTab(searchParams.get("tab"));
  const listHref =
    from === "admin" ? "/admin/skills" : customizeTabHref("skills");
  const pageHref =
    from === "admin" ? adminSkillHref(skillId) : skillHref(skillId);
  const mine = skill !== undefined && skill.owner?.id === user?.id;
  const enabled = listed
    ? enablement.enabledOf(listed)
    : (skill?.enabled ?? false);
  const notAdded =
    skill !== undefined &&
    !mine &&
    !enabled &&
    skill.can_toggle &&
    skill.published_version_number !== null;

  /** Whether the newest detail loaded. SWR's revalidating `mutate` keeps
   * the cached detail when the request fails, so read it here instead. */
  async function refresh(): Promise<boolean> {
    const lists = refreshSkillLists(mutate);
    if (!canEdit) {
      await lists;
      return true;
    }
    try {
      const fresh = await errorHandlingFetcher<SkillEditableDetail>(
        SWR_KEYS.editableSkill(skillId)
      );
      await Promise.all([detail.mutate(fresh, { revalidate: false }), lists]);
      return true;
    } catch {
      await lists;
      return false;
    }
  }

  function setEditing(next: boolean): void {
    navigation.go(next ? `${pageHref}?edit=1` : `${pageHref}?tab=contents`, {
      replace: true,
      scroll: false,
    });
  }

  async function setEnabled(next: boolean): Promise<void> {
    if (!skill) return;
    await enablement.setEnabled(listed ?? skill, next);
    if (canEdit) await detail.mutate();
  }

  async function remove(): Promise<void> {
    if (!skill || removing) return;
    setRemoving(true);
    try {
      await deleteUserSkill(skill.id);
      refreshLists();
      toast.success(skillCopy("editor.toasts.deleted", { name: skill.name }));
      navigation.go(listHref, { replace: true });
    } catch (failure) {
      toast.error(
        failure instanceof Error
          ? failure.message
          : skillCopy("editor.toasts.deleteFailed")
      );
    } finally {
      setRemoving(false);
    }
  }

  const updated = skill?.updated_at ? new Date(skill.updated_at) : null;
  const meta = skill
    ? t("meta", {
        owner: mine
          ? t("ownerYou")
          : t("ownerEmail", { email: skill.owner?.email ?? "" }),
        version: skill.current_version_number ?? 1,
        published:
          skill.published_version_number === null
            ? "none"
            : String(skill.published_version_number),
        updated: updated
          ? format.dateTime(updated, { month: "short", day: "numeric" })
          : "",
      })
    : undefined;

  const menu: DropdownMenuItem[] = skill
    ? [
        ...(canChangeContent
          ? [
              {
                kind: "action" as const,
                id: "edit",
                icon: SvgEdit,
                title: t("edit"),
                onSelect: () => setEditing(true),
              },
            ]
          : []),
        ...(skill.can_delete
          ? [
              {
                kind: "group" as const,
                items: [
                  {
                    kind: "action" as const,
                    id: "remove",
                    icon: SvgTrash,
                    title: t("remove"),
                    danger: true,
                    onSelect: () => removeModal.toggle(true),
                  },
                ],
              },
            ]
          : []),
      ]
    : [];
  const tabs: DetailTab<SkillPageTab>[] | null = skill
    ? [
        {
          value: "overview",
          label: t("tabs.overview"),
          content: (
            <DetailOverview
              descriptionLabel={t("overview.description")}
              description={skill.description || t("overview.noDescription")}
              facts={[
                {
                  label: t("overview.createdBy"),
                  value: mine ? t("ownerYouTitle") : (skill.owner?.email ?? ""),
                },
                {
                  label: t("overview.access"),
                  value: t("overview.accessValue", {
                    access:
                      skill.public_permission !== null
                        ? "organization"
                        : !skill.is_personal
                          ? "shared"
                          : mine
                            ? "personal"
                            : "private",
                  }),
                },
                {
                  label: t("overview.tools"),
                  value: t("overview.instructionsOnly"),
                },
              ]}
            />
          ),
        },
        {
          value: "contents",
          label: files
            ? t("tabs.contentsCount", { count: files.length + 1 })
            : t("tabs.contents"),
          content: preview.error ? (
            <Section alignItems="start" gap={2} height="auto">
              <MessageCard variant="error" title={t("contents.loadFailed")} />
              <Button
                prominence="secondary"
                onClick={() => void preview.mutate()}
              >
                {t("contents.retry")}
              </Button>
            </Section>
          ) : !canEdit && preview.isLoading ? (
            <IconLoader />
          ) : (
            <SkillContentsTab
              name={skill.name}
              description={skill.description}
              // A viewer may run the published version, not the current one.
              versionNumber={canEdit ? skill.current_version_number : null}
              instructions={instructions}
              files={files}
              detail={detail.data}
              locked={locked}
              editing={editing}
              onEditingChange={setEditing}
              onDirtyChange={setContentsDirty}
              confirmLeave={unsaved.requestLeave}
              onSaved={refresh}
            />
          ),
        },
        ...(canEdit && detail.data
          ? [
              {
                value: "versions" as const,
                label: t("tabs.versions"),
                content: (
                  <SkillVersionsTab
                    skill={detail.data}
                    canPublish={canChangeOrganizationAccess(
                      detail.data,
                      isGlobalHolder
                    )}
                    onChanged={() => void refresh()}
                  />
                ),
              },
            ]
          : []),
      ]
    : null;

  return (
    <CustomizeDetailLayout
      back={
        from === "admin" ? (
          <BackLink to="/admin/skills" label={t("backAdmin")} />
        ) : (
          <BackLink to={customizeTabHref("skills")} label={t("back")} />
        )
      }
      icon={skill ? skillIcon(skill) : undefined}
      title={skill?.name ?? t("title")}
      description={meta}
      tags={
        notAdded ? (
          <Badge title={t("fromOrganization")} />
        ) : listed?.required_for_user ? (
          <Badge title={t("required.label")} tooltip={t("required.tooltip")} />
        ) : undefined
      }
      loading={
        isPlugin ||
        list.isLoading ||
        (canEdit && detail.isLoading) ||
        // A skill made a moment ago can be missing from a stale list.
        (list.data !== undefined && !listed && list.isValidating)
      }
      error={
        // A failed background refresh keeps the loaded page, and an open
        // editor with it.
        (list.error && !list.data) ||
        (detail.error && !detail.data) ||
        (list.data && !listed && !list.isValidating)
          ? t("loadFailed")
          : false
      }
      tabs={tabs}
      tab={tab}
      onTabChange={(next) =>
        unsaved.requestLeave(() =>
          navigation.go(
            next === "overview" ? pageHref : `${pageHref}?tab=${next}`,
            { replace: true, scroll: false }
          )
        )
      }
      actions={
        skill
          ? [
              <CopyButton
                key="copy"
                tooltip={t("copyLink")}
                aria-label={t("copyLink")}
                getCopyText={() =>
                  new URL(skillHref(skill.id), window.location.origin).href
                }
              />,
              ...(canEdit && !listed?.marketplace?.personal
                ? [
                    <Button
                      key="share"
                      prominence="secondary"
                      icon={SvgShare}
                      onClick={() => setSharing(true)}
                    >
                      {t("share")}
                    </Button>,
                  ]
                : []),
              ...(menu.length > 0
                ? [
                    <Dropdown key="menu" align="end">
                      <Dropdown.Trigger asChild>
                        <Button
                          prominence="tertiary"
                          icon={SvgMoreHorizontal}
                          aria-label={t("menu")}
                          tooltip={t("menu")}
                        />
                      </Dropdown.Trigger>
                      <Dropdown.Data label={t("menu")} items={menu} />
                    </Dropdown>,
                  ]
                : []),
              notAdded ? (
                <Button
                  key="add"
                  disabled={enablement.isPending(skill.id)}
                  onClick={() => void setEnabled(true)}
                >
                  {t("add")}
                </Button>
              ) : (
                <Section key="switch" width="auto" height="auto" padding={1}>
                  <InputSwitch
                    aria-label={t("switch", { name: skill.name })}
                    checked={enabled}
                    disabled={
                      !skill.can_toggle || enablement.isPending(skill.id)
                    }
                    onCheckedChange={(checked) => void setEnabled(checked)}
                  />
                </Section>
              ),
            ]
          : undefined
      }
    >
      <SkillSwitchModal enablement={enablement} />
      <UnsavedChangesModal
        open={unsaved.confirmationOpen}
        onCancel={unsaved.cancelLeave}
        onDiscard={unsaved.discardAndLeave}
      />
      {skill && (
        <ShareSkillModal
          mode="edit"
          skillId={skill.id}
          fallbackTitle={skill.name}
          open={sharing}
          onClose={() => setSharing(false)}
          onSaved={() => void refresh()}
        />
      )}
      <removeModal.Provider>
        {skill && (
          <ConfirmEntityModal
            danger
            entityType={skillCopy("editor.deleteModal.entityType")}
            entityName={skill.name}
            additionalDetails={skillCopy("editor.delete.description")}
            actionButtonText={skillCopy(
              removing
                ? "editor.deleteModal.pendingLabel"
                : "editor.deleteModal.label"
            )}
            onClose={() => {
              if (!removing) removeModal.toggle(false);
            }}
            onSubmit={() => void remove()}
          />
        )}
      </removeModal.Provider>
    </CustomizeDetailLayout>
  );
}
