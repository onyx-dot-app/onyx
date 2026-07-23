"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import type { Route } from "next";
import {
  Button,
  InputTypeIn,
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
import TextSeparator from "@/refresh-components/TextSeparator";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import SkillCard, {
  type CustomSkillCardItem,
  type SkillCardItem,
} from "@/sections/cards/SkillCard";
import CreateSkillModal from "@/sections/modals/skills/CreateSkillModal";
import SkillPreviewModal from "@/sections/modals/SkillPreviewModal";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";
import { stageSkillCreationDraft } from "@/lib/skills/creationDraft";
import LineItem from "@/refresh-components/buttons/LineItem";
import { isSkillNameConflict, setSkillEnabled } from "@/lib/skills/api";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function SkillsPage() {
  const router = useRouter();
  const externalAppIdParam = useSearchParams().get("externalAppId");
  const focusedExternalAppId =
    externalAppIdParam !== null && /^\d+$/.test(externalAppIdParam)
      ? Number(externalAppIdParam)
      : null;
  const { data, error, isLoading, refresh } = useUserSkills();
  const [searchQuery, setSearchQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
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
        toast.error(
          `${item.name} was updated, but the skill list could not be refreshed.`
        );
      });
    } catch (error) {
      if (enabled && !replaceConflict && isSkillNameConflict(error)) {
        setPendingSwitchTarget(item);
        return;
      }
      toast.error(
        error instanceof Error
          ? error.message
          : `Failed to ${enabled ? "enable" : "disable"} ${item.name}`
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
      if (
        item.source === "custom" &&
        item.skill.external_app?.external_app_id === focusedExternalAppId
      ) {
        return item.skill.external_app.name;
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
        (focusedExternalAppId === null ||
          (item.source === "custom" &&
            item.skill.external_app?.external_app_id ===
              focusedExternalAppId)) &&
        (!q ||
          item.name.toLowerCase().includes(q) ||
          item.description.toLowerCase().includes(q))
    );
  }, [focusedExternalAppId, items, searchQuery]);
  const previewUnavailableReason = (() => {
    if (previewTarget?.source === "builtin" && !previewTarget.is_available) {
      return (
        previewTarget.unavailable_reason ??
        "This skill is currently unavailable."
      );
    }
    if (
      previewTarget?.source === "custom" &&
      previewTarget.enabled &&
      previewTarget.skill.external_app &&
      !previewTarget.skill.external_app.ready
    ) {
      const dependency = previewTarget.skill.external_app;
      return dependency.enabled
        ? `Connect app “${dependency.name}” from the Apps page to use this skill.`
        : `App “${dependency.name}” is disabled by an administrator.`;
    }
    return null;
  })();
  const switchPending =
    pendingSwitchTarget !== null && pendingSkillIds.has(pendingSwitchTarget.id);
  const enabledNameConflict =
    pendingSwitchTarget === null
      ? null
      : (enabledItemByName.get(pendingSwitchTarget.name) ?? null);
  const switchImpact = (() => {
    if (pendingSwitchTarget?.source !== "custom") {
      return "Continuing will disable the active skill and enable the selected one.";
    }
    const targetApp = pendingSwitchTarget.skill.external_app;
    if (!targetApp) {
      return "Continuing will disable the active skill and enable the selected one.";
    }
    let currentSkill = "the currently enabled skill";
    if (
      enabledNameConflict?.source === "custom" &&
      enabledNameConflict.skill.external_app
    ) {
      currentSkill = `the skill that uses app “${enabledNameConflict.skill.external_app.name}”`;
    } else if (
      enabledNameConflict?.source === "custom" &&
      enabledNameConflict.is_personal
    ) {
      currentSkill = "your personal skill";
    }
    return `Switching will disable ${currentSkill} and enable the skill that uses app “${targetApp.name}”.`;
  })();

  return (
    <SettingsLayouts.Root data-testid="SkillsPage/container">
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title="Skills"
        description="Capability bundles your Craft agent can reach for. This page shows built-in skills, skills shared with you, and your own personal skills."
        rightChildren={
          <Popover open={createMenuOpen} onOpenChange={setCreateMenuOpen}>
            <Popover.Trigger asChild>
              <Button icon={SvgPlus}>Create skill</Button>
            </Popover.Trigger>
            <Popover.Content align="end" sideOffset={4} width="xl">
              <Popover.Menu>
                <LineItem
                  icon={SvgEdit}
                  description="Write the instructions and add supporting files in Onyx."
                  wrapDescription
                  onClick={() => {
                    setCreateMenuOpen(false);
                    router.push("/craft/v1/skills/new" as Route);
                  }}
                >
                  Start from scratch
                </LineItem>
                <LineItem
                  icon={SvgUploadCloud}
                  description="Import a SKILL.md file, ZIP file, or skill folder."
                  wrapDescription
                  onClick={() => {
                    setCreateMenuOpen(false);
                    setCreateOpen(true);
                  }}
                >
                  Upload a skill
                </LineItem>
              </Popover.Menu>
            </Popover.Content>
          </Popover>
        }
      >
        <InputTypeIn
          ref={searchInputRef}
          placeholder="Search skills..."
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          searchIcon
        />
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        {focusedAppName && (
          <MessageCard
            variant="info"
            title={`Skills for app “${focusedAppName}”`}
            description={`Enable every skill associated with app “${focusedAppName}”. The app may not work correctly without them. If another skill with the same name is enabled, enabling the app-associated skill disables the other skill for you.`}
            rightChildren={
              <Button prominence="secondary" href="/craft/v1/skills">
                Show all skills
              </Button>
            }
          />
        )}

        {isLoading && <SvgSimpleLoader />}

        {error && !isLoading && (
          <MessageCard
            variant="error"
            title="Failed to load skills"
            description="Check the console for details and try refreshing the page."
          />
        )}

        {!isLoading && !error && (
          <>
            {visibleItems.length === 0 ? (
              <IllustrationContent
                illustration={SvgNoResult}
                title={
                  items.length === 0
                    ? "No skills available"
                    : "No matching skills"
                }
                description={
                  items.length === 0
                    ? "No custom skills have been shared with you yet, and no built-ins are configured."
                    : "Try a different search."
                }
              />
            ) : (
              <>
                <section className="flex flex-col gap-2">
                  <Text font="secondary-body" color="text-03">
                    Browse skills
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
                  text={visibleItems.length === 1 ? "Skill" : "Skills"}
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
          title={`Switch “${pendingSwitchTarget.name}” skill?`}
          description={`Only one skill named “${pendingSwitchTarget.name}” can be enabled at a time.`}
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
              {switchPending ? "Switching..." : "Switch skill"}
            </Button>
          }
        >
          {switchImpact}
        </ConfirmationModalLayout>
      )}
    </SettingsLayouts.Root>
  );
}
