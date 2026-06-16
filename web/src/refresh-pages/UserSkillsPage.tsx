"use client";

import { useMemo, useRef, useState } from "react";
import { Button, InputTypeIn, MessageCard, Text } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgBlocks, SvgPlus, SvgSettings, SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import TextSeparator from "@/refresh-components/TextSeparator";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import { useUser } from "@/providers/UserProvider";
import SkillCard, {
  type CustomSkillCardItem,
  type SkillCardItem,
} from "@/sections/cards/SkillCard";
import CreatePersonalSkillModal from "@/refresh-pages/UserSkillsPage/CreatePersonalSkillModal";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";
import {
  deleteUserSkill,
  patchUserSkill,
  replaceUserSkillBundle,
} from "@/lib/skills/api";
import { toast } from "@/hooks/useToast";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UserSkillsPage() {
  const { data, error, isLoading, refresh } = useUserSkills();
  const { user, isAdmin } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<CustomSkillCardItem | null>(
    null
  );
  const searchInputRef = useRef<HTMLInputElement>(null);
  const replaceBundleTarget = useRef<CustomSkillCardItem | null>(null);
  const replaceFileRef = useRef<HTMLInputElement>(null);
  // Non-null while a card mutation is in flight; gates all card actions so a
  // shared file picker can't be retargeted and toggles can't race.
  const [pendingId, setPendingId] = useState<string | null>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  function handleReplaceBundleClick(item: CustomSkillCardItem) {
    if (pendingId) return;
    replaceBundleTarget.current = item;
    replaceFileRef.current?.click();
  }

  async function handleReplaceBundleFile(
    event: React.ChangeEvent<HTMLInputElement>
  ) {
    const target = replaceBundleTarget.current;
    const file = event.target.files?.[0];
    event.target.value = "";
    replaceBundleTarget.current = null;
    if (!target || !file) return;

    setPendingId(target.id);
    try {
      await replaceUserSkillBundle(target.id, file);
      toast.success(`Replaced bundle for "${target.name}"`);
      refresh();
    } catch (err) {
      console.error("Failed to replace skill bundle", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to replace bundle"
      );
    } finally {
      setPendingId(null);
    }
  }

  async function handleToggleEnabled(
    item: CustomSkillCardItem,
    enabled: boolean
  ) {
    setPendingId(item.id);
    try {
      await patchUserSkill(item.id, enabled);
      toast.success(`${enabled ? "Enabled" : "Disabled"} "${item.name}"`);
      refresh();
    } catch (err) {
      console.error("Failed to toggle skill", err);
      toast.error(err instanceof Error ? err.message : "Failed to toggle");
    } finally {
      setPendingId(null);
    }
  }

  async function handleDeleteConfirmed() {
    const target = deleteTarget;
    if (!target) return;
    setDeleteTarget(null);

    setPendingId(target.id);
    try {
      await deleteUserSkill(target.id);
      toast.success(`Deleted "${target.name}"`);
      refresh();
    } catch (err) {
      console.error("Failed to delete skill", err);
      toast.error(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setPendingId(null);
    }
  }

  const items = useMemo<SkillCardItem[]>(() => {
    if (!data) return [];
    const builtinItems: SkillCardItem[] = data.builtins.map((b) => ({
      id: `builtin:${b.slug}`,
      name: b.name,
      description: b.description,
      source: "builtin",
      is_available: b.is_available,
      unavailable_reason: b.unavailable_reason,
    }));
    const customItems: SkillCardItem[] = data.customs.map((c) => ({
      id: c.id,
      name: c.name,
      description: c.description,
      source: "custom",
      author_email: c.author_email,
      is_personal:
        c.is_personal && user !== null && c.author_user_id === user.id,
      enabled: c.enabled,
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
  }, [data, user]);

  const visibleItems = useMemo(() => {
    const q = searchQuery.trim().toLowerCase();
    if (!q) return items;
    return items.filter(
      (item) =>
        item.name.toLowerCase().includes(q) ||
        item.description.toLowerCase().includes(q)
    );
  }, [items, searchQuery]);

  return (
    <SettingsLayouts.Root data-testid="UserSkillsPage/container">
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title="Skills"
        description="Capability bundles your Craft agent can reach for. This page shows what's currently available to you — skills granted by admins plus your own personal skills."
        rightChildren={
          <div className="flex items-center gap-2">
            {isAdmin && (
              <Button
                href="/craft/v1/skills/manage"
                prominence="secondary"
                icon={SvgSettings}
              >
                Manage skills
              </Button>
            )}
            <Button icon={SvgPlus} onClick={() => setCreateOpen(true)}>
              Create skill
            </Button>
          </div>
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
                    ? "Your admin hasn't granted you access to any custom skills yet, and no built-ins are configured."
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
                        busy={pendingId !== null}
                        onReplaceBundle={handleReplaceBundleClick}
                        onDelete={setDeleteTarget}
                        onToggleEnabled={handleToggleEnabled}
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

            {visibleItems.length > 0 && (
              <div className="pt-2">
                <Text as="p" font="secondary-body" color="text-03">
                  Org-wide skills are managed by admins. Personal skills you
                  create are visible only to you.
                </Text>
              </div>
            )}
          </>
        )}
      </SettingsLayouts.Body>

      {/* Inline file picker for the card-level "Replace bundle" action. */}
      <input
        ref={replaceFileRef}
        type="file"
        accept=".zip,application/zip"
        className="hidden"
        onChange={handleReplaceBundleFile}
      />

      <CreatePersonalSkillModal
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={refresh}
      />

      {deleteTarget && (
        <ConfirmEntityModal
          danger
          entityType="skill"
          entityName={deleteTarget.name}
          onClose={() => setDeleteTarget(null)}
          onSubmit={handleDeleteConfirmed}
        />
      )}
    </SettingsLayouts.Root>
  );
}
