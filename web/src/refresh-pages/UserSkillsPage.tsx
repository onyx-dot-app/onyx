"use client";

import { useMemo, useRef, useState } from "react";
import { Button, InputTypeIn, MessageCard, Text } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgBlocks, SvgSettings, SvgSimpleLoader } from "@opal/icons";
import { SettingsLayouts } from "@opal/layouts";
import TextSeparator from "@/refresh-components/TextSeparator";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import { useUser } from "@/providers/UserProvider";
import SkillCard, { type SkillCardItem } from "@/sections/cards/SkillCard";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UserSkillsPage() {
  const { data, error, isLoading } = useUserSkills();
  const { isAdmin } = useUser();
  const [searchQuery, setSearchQuery] = useState("");
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

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
    }));
    return [...builtinItems, ...customItems];
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
        description="Capability bundles your Craft agent can reach for. Skills are granted by admins; this page shows what's currently available to you."
        rightChildren={
          isAdmin ? (
            <div className="flex items-center gap-2">
              <Button
                href="/craft/v1/skills/manage"
                prominence="secondary"
                icon={SvgSettings}
              >
                Manage skills
              </Button>
            </div>
          ) : undefined
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
                      <SkillCard key={item.id} item={item} />
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
                  Skills are managed by org admins. To request a new custom
                  skill, talk to your Onyx admin.
                </Text>
              </div>
            )}
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
