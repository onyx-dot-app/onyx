"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import {
  Button,
  InputTypeIn,
  LineItemButton,
  MessageCard,
  Popover,
  Text,
} from "@opal/components";
import {
  ConfirmationModalLayout,
  IllustrationContent,
  SettingsLayouts,
  toast,
} from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import {
  SvgAlertTriangle,
  SvgBlocks,
  SvgEdit,
  SvgPlus,
  SvgSimpleLoader,
  SvgUploadCloud,
} from "@opal/icons";
import { SvgGithub } from "@opal/logos";
import TextSeparator from "@/refresh-components/TextSeparator";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import SkillCard, {
  type CustomSkillCardItem,
  type SkillCardItem,
} from "@/sections/cards/SkillCard";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import ImportSkillsFromGitHubModal from "@/sections/modals/skills/ImportSkillsFromGitHubModal";
import SkillPreviewModal from "@/sections/modals/SkillPreviewModal";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import { isSkillNameConflict, setSkillEnabled } from "@/lib/skills/api";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SkillsPage() {
  const t = useTranslations("skills");
  const router = useRouter();
  const externalAppIdParam = useSearchParams().get("externalAppId");
  const focusedExternalAppId =
    externalAppIdParam !== null && /^\d+$/.test(externalAppIdParam)
      ? Number(externalAppIdParam)
      : null;
  const { data, error, isLoading, refresh } = useUserSkills();
  const [searchQuery, setSearchQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [githubImportOpen, setGitHubImportOpen] = useState(false);
  const [createMenuOpen, setCreateMenuOpen] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<SkillCardItem | null>(
    null
  );
  const [pendingSkillIds, setPendingSkillIds] = useState<Set<string>>(
    new Set()
  );
  const [optimisticEnabledById, setOptimisticEnabledById] = useState<
    Map<string, boolean>
  >(new Map());
  const [pendingSwitchTarget, setPendingSwitchTarget] =
    useState<SkillCardItem | null>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  function handleEdit(item: CustomSkillCardItem) {
    router.push(`/craft/v1/skills/edit/${item.id}` as Route);
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
      if (replaceConflict) setPendingSwitchTarget(null);
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
          b.source === "builtin" && b.is_available !== null
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
    // Group order: built-in, then custom (org-wide), then personal; alphabetical within each group.
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
  }, [data, optimisticEnabledById]);

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

  const visibleItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    return items.filter(
      (item) =>
        (focusedAppName === null ||
          item.external_app?.external_app_id === focusedExternalAppId) &&
        (!q ||
          item.name.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q))
    );
  }, [focusedAppName, focusedExternalAppId, items, searchQuery]);

  const switchPending =
    pendingSwitchTarget !== null && pendingSkillIds.has(pendingSwitchTarget.id);
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
        description={t("page.header.description")}
        rightChildren={
          <Popover open={createMenuOpen} onOpenChange={setCreateMenuOpen}>
            <Popover.Trigger asChild>
              <Button icon={SvgPlus}>
                {t("page.createMenu.trigger.label")}
              </Button>
            </Popover.Trigger>
            <Popover.Content align="end" sideOffset={4} width="xl">
              <Popover.Menu>
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  icon={SvgEdit}
                  description={t("page.createMenu.scratch.description")}
                  onClick={() => {
                    setCreateMenuOpen(false);
                    router.push("/craft/v1/skills/new" as Route);
                  }}
                  title={t("page.createMenu.scratch.title")}
                />
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  icon={SvgUploadCloud}
                  description={t("page.createMenu.upload.description")}
                  onClick={() => {
                    setCreateMenuOpen(false);
                    setCreateOpen(true);
                  }}
                  title={t("page.createMenu.upload.title")}
                />
                <LineItemButton
                  sizePreset="main-ui"
                  rounding={2}
                  icon={SvgGithub}
                  description={t("page.createMenu.github.description")}
                  onClick={() => {
                    setCreateMenuOpen(false);
                    setGitHubImportOpen(true);
                  }}
                  title={t("page.createMenu.github.title")}
                />
              </Popover.Menu>
            </Popover.Content>
          </Popover>
        }
      >
        <InputTypeIn
          ref={searchInputRef}
          placeholder={t("page.search.placeholder")}
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          searchIcon
        />
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        {focusedAppName && (
          <MessageCard
            variant="info"
            title={t("page.focusedApp.title", { appName: focusedAppName })}
            description={t("page.focusedApp.description", {
              appName: focusedAppName,
            })}
            rightChildren={
              <Button prominence="secondary" href="/craft/v1/skills">
                {t("page.focusedApp.showAll.label")}
              </Button>
            }
          />
        )}

        {isLoading && <SvgSimpleLoader />}

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
                    : t("page.empty.noMatches.description")
                }
              />
            ) : (
              <>
                <section className="flex flex-col gap-2">
                  <Text font="secondary-body" color="text-03">
                    {t("page.browse.title")}
                  </Text>
                  <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
                    {visibleItems.map((item) => (
                      <SkillCard
                        key={item.id}
                        item={item}
                        hasEnabledNameConflict={
                          !item.enabled && enabledItemByName.has(item.name)
                        }
                        onEdit={handleEdit}
                        onClick={setPreviewTarget}
                        onEnabledChange={(skill, enabled) =>
                          void updateSkillEnabled(skill, enabled)
                        }
                        enablementPending={pendingSkillIds.has(item.id)}
                      />
                    ))}
                  </div>
                </section>
                <TextSeparator
                  count={visibleItems.length}
                  text={t("page.countSeparator.label", {
                    count: visibleItems.length,
                  })}
                />
              </>
            )}
          </>
        )}
      </SettingsLayouts.Body>

      <CreateSkillModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onContinue={(draft) => {
          const draftId = stageSkillCreationDraft(draft);
          setCreateOpen(false);
          router.push(`/craft/v1/skills/new?draft=${draftId}` as Route);
        }}
      />

      {githubImportOpen && (
        <ImportSkillsFromGitHubModal
          open
          onClose={() => setGitHubImportOpen(false)}
          onImported={() => {
            void refresh().catch((refreshError: unknown) => {
              console.error(
                "Failed to refresh skills after GitHub import",
                refreshError
              );
            });
          }}
        />
      )}

      <SkillPreviewModal
        open={previewTarget !== null}
        skillId={previewTarget?.id ?? null}
        fallbackTitle={previewTarget?.name}
        unavailableReason={previewUnavailableReason}
        onClose={() => setPreviewTarget(null)}
      />

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
            switchPending ? undefined : () => setPendingSwitchTarget(null)
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
    </SettingsLayouts.Root>
  );
}
