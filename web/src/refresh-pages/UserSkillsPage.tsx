"use client";

import { useMemo, useRef, useState } from "react";
import { Button, FilterButton, LineItemButton } from "@opal/components";
import { Popover, PopoverMenu } from "@opal/components";
import { SvgBlocks, SvgPlus, SvgUser } from "@opal/icons";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import Text from "@/refresh-components/texts/Text";
import Tabs from "@/refresh-components/Tabs";
import TextSeparator from "@/refresh-components/TextSeparator";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import useOnMount from "@/hooks/useOnMount";
import useFilter from "@/hooks/useFilter";
import { toast } from "@/hooks/useToast";
import SkillCard, { type SkillCardItem } from "@/sections/cards/SkillCard";
import UploadSkillModal from "@/refresh-pages/admin/SkillsPage/UploadSkillModal";
import ShareSkillModal from "@/refresh-pages/admin/SkillsPage/ShareSkillModal";
import InspectSkillModal from "@/refresh-pages/admin/SkillsPage/InspectSkillModal";
import {
  MOCK_BUILTIN_SKILLS,
  MOCK_CUSTOM_SKILLS,
  MOCK_CURRENT_USER,
  ONYX_BUILTIN_AUTHOR,
} from "@/refresh-pages/admin/SkillsPage/mockData";
import type {
  CustomSkill,
  SkillAuthor,
  SkillVisibility,
} from "@/refresh-pages/admin/SkillsPage/interfaces";

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function UserSkillsPage() {
  // Local copy of skills so wireframe edits show up immediately.
  const [allSkills, setAllSkills] = useState<CustomSkill[]>(MOCK_CUSTOM_SKILLS);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [shareTarget, setShareTarget] = useState<CustomSkill | null>(null);
  const [inspectTarget, setInspectTarget] = useState<CustomSkill | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"all" | "your">("all");
  const [selectedAuthorIds, setSelectedAuthorIds] = useState<Set<string>>(
    new Set()
  );
  const searchInputRef = useRef<HTMLInputElement>(null);

  useOnMount(() => {
    searchInputRef.current?.focus();
  });

  // -- Build the unified list of display items ------------------------------

  const builtinItems = useMemo<SkillCardItem[]>(
    () =>
      MOCK_BUILTIN_SKILLS.map((skill) => ({
        id: `builtin:${skill.slug}`,
        name: skill.name,
        description: skill.description,
        author: ONYX_BUILTIN_AUTHOR,
        source: "builtin",
        available: skill.available,
        unavailable_reason: skill.unavailable_reason,
      })),
    []
  );

  const customItems = useMemo<SkillCardItem[]>(
    () =>
      allSkills
        .filter((skill) => {
          if (skill.author.id === MOCK_CURRENT_USER.id) return true;
          // Treat shared / org-wide skills as visible to the current user.
          if (!skill.enabled) return false;
          return (
            skill.visibility === "org_wide" ||
            skill.visibility === "groups" ||
            skill.visibility === "users_and_groups" ||
            skill.visibility === "users"
          );
        })
        .map((skill) => ({
          id: skill.id,
          name: skill.name,
          description: skill.description,
          author: skill.author,
          source: skill.author.id === MOCK_CURRENT_USER.id ? "owned" : "shared",
          customSkill: skill,
        })),
    [allSkills]
  );

  const allItems = useMemo<SkillCardItem[]>(
    () => [...builtinItems, ...customItems],
    [builtinItems, customItems]
  );

  // -- Author filter data ---------------------------------------------------

  const uniqueAuthors = useMemo<SkillAuthor[]>(() => {
    const seen = new Map<string, SkillAuthor>();
    for (const item of allItems) {
      if (!seen.has(item.author.id)) seen.set(item.author.id, item.author);
    }
    // Sort: Onyx first, then current user, then everyone else alphabetically.
    return Array.from(seen.values()).sort((a, b) => {
      if (a.id === ONYX_BUILTIN_AUTHOR.id) return -1;
      if (b.id === ONYX_BUILTIN_AUTHOR.id) return 1;
      if (a.id === MOCK_CURRENT_USER.id) return -1;
      if (b.id === MOCK_CURRENT_USER.id) return 1;
      return a.email.localeCompare(b.email);
    });
  }, [allItems]);

  const authorFilter = useFilter(uniqueAuthors, (a) => a.email);

  const authorFilterButtonText = useMemo(() => {
    if (selectedAuthorIds.size === 0) return "Anyone";
    if (selectedAuthorIds.size === 1) {
      const selectedId = Array.from(selectedAuthorIds)[0];
      const author = uniqueAuthors.find((a) => a.id === selectedId);
      return author ? `By ${author.email}` : "Anyone";
    }
    return `${selectedAuthorIds.size} authors`;
  }, [selectedAuthorIds, uniqueAuthors]);

  // -- Apply search + tab + author filters ----------------------------------

  const visibleItems = useMemo(() => {
    const lowerQuery = searchQuery.trim().toLowerCase();

    return allItems.filter((item) => {
      const tabMatch = activeTab === "all" ? true : item.source === "owned";

      const authorMatch =
        selectedAuthorIds.size === 0 || selectedAuthorIds.has(item.author.id);

      const searchMatch =
        !lowerQuery ||
        item.name.toLowerCase().includes(lowerQuery) ||
        item.description.toLowerCase().includes(lowerQuery) ||
        item.author.email.toLowerCase().includes(lowerQuery);

      return tabMatch && authorMatch && searchMatch;
    });
  }, [allItems, activeTab, selectedAuthorIds, searchQuery]);

  // -- Mutations ------------------------------------------------------------

  function patchSkill(
    skillId: string,
    patcher: (skill: CustomSkill) => CustomSkill
  ) {
    setAllSkills((prev) =>
      prev.map((s) => (s.id === skillId ? patcher(s) : s))
    );
  }

  function handleUpload(input: {
    file: File | null;
    slug: string;
    name: string;
    description: string;
    visibility: SkillVisibility;
  }) {
    setUploadOpen(false);
    toast.success(`Uploaded "${input.name}" (wireframe — no backend)`);
    const newSkill: CustomSkill = {
      id: `skill-new-${Date.now()}`,
      slug: input.slug,
      name: input.name,
      description: input.description,
      author: MOCK_CURRENT_USER,
      visibility:
        input.visibility === "org_wide" ? "private" : input.visibility,
      shared_user_count: 0,
      shared_group_count: 0,
      enabled: true,
      promotion_requested: false,
      promoted_by_admin: false,
      bundle: {
        sha256: "0".repeat(64),
        total_bytes: input.file?.size ?? 0,
        files: [
          {
            path: "SKILL.md",
            size_bytes: 1_024,
            executable: false,
            kind: "markdown",
          },
        ],
      },
      updated_at: new Date().toISOString(),
    };
    setAllSkills((prev) => [newSkill, ...prev]);
  }

  function handleShareSave(visibility: SkillVisibility) {
    if (!shareTarget) return;
    if (visibility === "org_wide") {
      toast.info(
        "Org-wide is admin-only. Use Request org-wide to flag for promotion."
      );
      return;
    }
    patchSkill(shareTarget.id, (skill) => ({ ...skill, visibility }));
    toast.success(`Updated "${shareTarget.name}" sharing`);
  }

  function handleRequestOrgWide() {
    if (!shareTarget) return;
    patchSkill(shareTarget.id, (skill) => ({
      ...skill,
      promotion_requested: true,
    }));
    toast.success(`Requested org-wide promotion for "${shareTarget.name}"`);
  }

  function handleDelete(skill: CustomSkill) {
    setAllSkills((prev) => prev.filter((s) => s.id !== skill.id));
    toast.success(`Deleted "${skill.name}"`);
  }

  function handleInspect(item: SkillCardItem) {
    if (item.customSkill) {
      setInspectTarget(item.customSkill);
    }
    // Built-ins aren't inspectable in v1 — clicking is a no-op.
  }

  // -- Render ---------------------------------------------------------------

  return (
    <SettingsLayouts.Root data-testid="UserSkillsPage/container">
      <SettingsLayouts.Header
        icon={SvgBlocks}
        title="Skills"
        description="Capability bundles your Craft agent can reach for — built-in, shared with you, and your own."
        rightChildren={
          <Button icon={SvgPlus} onClick={() => setUploadOpen(true)}>
            Upload skill
          </Button>
        }
      >
        <div className="flex flex-col gap-2">
          <div className="flex flex-row items-center gap-2">
            <div className="flex-2">
              <InputTypeIn
                ref={searchInputRef}
                placeholder="Search skills..."
                value={searchQuery}
                onChange={(event) => setSearchQuery(event.target.value)}
                leftSearchIcon
              />
            </div>
            <div className="flex-1">
              <Tabs
                value={activeTab}
                onValueChange={(value) => setActiveTab(value as "all" | "your")}
              >
                <Tabs.List>
                  <Tabs.Trigger value="all">All Skills</Tabs.Trigger>
                  <Tabs.Trigger value="your">Your Skills</Tabs.Trigger>
                </Tabs.List>
              </Tabs>
            </div>
          </div>
          <div className="flex flex-row gap-2">
            <Popover>
              <Popover.Trigger asChild>
                <FilterButton
                  icon={SvgUser}
                  active={selectedAuthorIds.size > 0}
                  onClear={() => setSelectedAuthorIds(new Set())}
                >
                  {authorFilterButtonText}
                </FilterButton>
              </Popover.Trigger>
              <Popover.Content align="start">
                <PopoverMenu>
                  {[
                    <InputTypeIn
                      key="author-search"
                      placeholder="Filter authors..."
                      variant="internal"
                      leftSearchIcon
                      value={authorFilter.query}
                      onChange={(e) => authorFilter.setQuery(e.target.value)}
                    />,
                    ...authorFilter.filtered.map((author) => {
                      const isSelected = selectedAuthorIds.has(author.id);
                      const isCurrentUser = author.id === MOCK_CURRENT_USER.id;
                      const isOnyx = author.id === ONYX_BUILTIN_AUTHOR.id;
                      const description = isOnyx
                        ? "Built-in skills"
                        : isCurrentUser
                          ? "Me"
                          : undefined;
                      return (
                        <LineItemButton
                          key={author.id}
                          sizePreset="main-ui"
                          rounding="sm"
                          selectVariant="select-heavy"
                          icon={SvgUser}
                          title={author.email}
                          description={description}
                          state={isSelected ? "selected" : "empty"}
                          onClick={() => {
                            setSelectedAuthorIds((prev) => {
                              const next = new Set(prev);
                              if (next.has(author.id)) {
                                next.delete(author.id);
                              } else {
                                next.add(author.id);
                              }
                              return next;
                            });
                          }}
                        />
                      );
                    }),
                  ]}
                </PopoverMenu>
              </Popover.Content>
            </Popover>
          </div>
        </div>
      </SettingsLayouts.Header>

      <SettingsLayouts.Body>
        {visibleItems.length === 0 ? (
          <Text
            as="p"
            className="w-full h-full flex flex-col items-center justify-center py-12"
            text03
          >
            No Skills found
          </Text>
        ) : (
          <>
            <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
              {visibleItems.map((item) => (
                <SkillCard
                  key={item.id}
                  item={item}
                  onInspect={handleInspect}
                  onShare={setShareTarget}
                  onReplaceBundle={(skill) =>
                    toast.info(
                      `Replace bundle for "${skill.name}" (wireframe — would open a file picker)`
                    )
                  }
                  onDelete={handleDelete}
                />
              ))}
            </div>
            <TextSeparator
              count={visibleItems.length}
              text={visibleItems.length === 1 ? "Skill" : "Skills"}
            />
          </>
        )}
      </SettingsLayouts.Body>

      <UploadSkillModal
        open={uploadOpen}
        onClose={() => setUploadOpen(false)}
        canSetOrgWide={false}
        onUpload={handleUpload}
      />

      <ShareSkillModal
        skill={shareTarget}
        open={shareTarget !== null}
        onClose={() => setShareTarget(null)}
        canSetOrgWide={false}
        onSave={handleShareSave}
        onRequestOrgWide={handleRequestOrgWide}
      />

      <InspectSkillModal
        skill={inspectTarget}
        open={inspectTarget !== null}
        onClose={() => setInspectTarget(null)}
        onReplaceBundle={
          inspectTarget?.author.id === MOCK_CURRENT_USER.id
            ? () =>
                toast.info(
                  "Replace bundle (wireframe — would open file picker)"
                )
            : undefined
        }
        onDownload={() => toast.info("Download zip (wireframe)")}
      />
    </SettingsLayouts.Root>
  );
}
