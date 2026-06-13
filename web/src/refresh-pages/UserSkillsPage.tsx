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
        title="技能"
        description="技能是 Glomi 创作智能体可调用的能力包。管理员授予技能后，你可以在这里查看当前可用的能力。"
        rightChildren={
          isAdmin ? (
            <div className="flex items-center gap-2">
              <Button
                href="/craft/v1/skills/manage"
                prominence="secondary"
                icon={SvgSettings}
              >
                管理技能
              </Button>
            </div>
          ) : undefined
        }
      >
        <InputTypeIn
          ref={searchInputRef}
          placeholder="搜索技能..."
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
            title="技能加载失败"
            description="请查看控制台详情，或刷新页面后重试。"
          />
        )}

        {!isLoading && !error && (
          <>
            {visibleItems.length === 0 ? (
              <IllustrationContent
                illustration={SvgNoResult}
                title={
                  items.length === 0
                    ? "暂无可用技能"
                    : "没有匹配的技能"
                }
                description={
                  items.length === 0
                    ? "管理员还没有为你授权自定义技能，也尚未配置内置技能。"
                    : "换个关键词试试。"
                }
              />
            ) : (
              <>
                <section className="flex flex-col gap-2">
                  <Text font="secondary-body" color="text-03">
                    浏览技能
                  </Text>
                  <div className="w-full grid grid-cols-1 md:grid-cols-2 gap-2">
                    {visibleItems.map((item) => (
                      <SkillCard key={item.id} item={item} />
                    ))}
                  </div>
                </section>
                <TextSeparator
                  count={visibleItems.length}
                  text="技能"
                />
              </>
            )}

            {visibleItems.length > 0 && (
              <div className="pt-2">
                <Text as="p" font="secondary-body" color="text-03">
                  技能由组织管理员管理。如需申请新的自定义技能，请联系你的
                  Glomi AI 管理员。
                </Text>
              </div>
            )}
          </>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
