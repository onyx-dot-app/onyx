"use client";

import { useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import { Button, InputTypeIn, MessageCard, Text } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgBlocks, SvgPlus, SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import TextSeparator from "@/refresh-components/TextSeparator";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import { useUser } from "@/providers/UserProvider";
import SkillCard, {
  type CustomSkillCardItem,
  type SkillCardItem,
} from "@/sections/cards/SkillCard";
import CreatePersonalSkillModal from "@/views/UserSkillsPage/CreatePersonalSkillModal";
import UploadSkillModal from "@/sections/modals/skills/UploadSkillModal";
import SkillPreviewModal from "@/sections/modals/SkillPreviewModal";
import type { BuiltinSkill, CustomSkill } from "@/lib/skills/types";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UserSkillsPage() {
  const router = useRouter();
  const { data, error, isLoading, refresh } = useUserSkills();
  const { isAdmin, isCurator } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const [personalCreateOpen, setPersonalCreateOpen] = useState(false);
  const [orgUploadOpen, setOrgUploadOpen] = useState(false);
  const [previewTarget, setPreviewTarget] = useState<SkillCardItem | null>(
    null
  );
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  const canManageOrgSkills = isAdmin || isCurator;

  function handleCreateClick() {
    if (canManageOrgSkills) {
      setOrgUploadOpen(true);
    } else {
      setPersonalCreateOpen(true);
    }
  }

  function handleEdit(item: CustomSkillCardItem) {
    router.push(`/craft/v1/skills/edit/${item.id}` as Route);
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
        is_available: b.is_available,
        unavailable_reason: b.unavailable_reason,
      }));
    const customItems: SkillCardItem[] = data.customs
      .filter(
        (c): c is CustomSkill =>
          c.source === "custom" && c.is_public !== null && c.enabled !== null
      )
      .map((c) => ({
        id: c.id,
        name: c.name,
        description: c.description,
        source: "custom",
        skill: c,
        author_email: c.author_email,
        is_personal: c.is_personal && c.user_permission === "OWNER",
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
  }, [data]);

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
        description="Capability bundles your Craft agent can reach for. This page shows built-in skills, skills shared with you, and your own personal skills."
        rightChildren={
          <div className="flex items-center gap-2">
            <Button icon={SvgPlus} onClick={handleCreateClick}>
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
                        onEdit={handleEdit}
                        onClick={setPreviewTarget}
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

      <CreatePersonalSkillModal
        open={personalCreateOpen}
        onClose={() => setPersonalCreateOpen(false)}
        onCreated={refresh}
      />

      <UploadSkillModal
        open={orgUploadOpen}
        onClose={() => setOrgUploadOpen(false)}
        onUploaded={refresh}
      />

      <SkillPreviewModal
        open={previewTarget !== null}
        skillId={previewTarget?.id ?? null}
        fallbackTitle={previewTarget?.name}
        onClose={() => setPreviewTarget(null)}
      />
    </SettingsLayouts.Root>
  );
}
