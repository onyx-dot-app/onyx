"use client";

import { useMemo, useRef, useState } from "react";
import { MessageCard } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import { SvgBlocks } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Text from "@/refresh-components/texts/Text";
import TextSeparator from "@/refresh-components/TextSeparator";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import useOnMount from "@/hooks/useOnMount";
import useUserSkills from "@/hooks/useUserSkills";
import SkillCard, { type SkillCardItem } from "@/sections/cards/SkillCard";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UserSkillsPage() {
  const { data, error, isLoading } = useUserSkills();
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
      >
        <InputTypeIn
          ref={searchInputRef}
          placeholder="Search skills..."
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          leftSearchIcon
        />
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        {isLoading && <SimpleLoader />}

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
                <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
                  {visibleItems.map((item) => (
                    <SkillCard key={item.id} item={item} />
                  ))}
                </div>
                <TextSeparator
                  count={visibleItems.length}
                  text={visibleItems.length === 1 ? "Skill" : "Skills"}
                />
              </>
            )}

            {visibleItems.length > 0 && (
              <Text as="p" secondaryBody text03 className="pt-2">
                Skills are managed by org admins. To request a new custom skill,
                talk to your Onyx admin.
              </Text>
            )}
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
