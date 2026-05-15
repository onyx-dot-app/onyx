"use client";

import { useCallback } from "react";
import { Tag } from "@opal/components";
import { SvgBlocks, SvgEdit, SvgShare, SvgTrash, SvgUser } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import { noProp } from "@/lib/utils";
import { CardItemLayout } from "@/layouts/general-layouts";
import { Content } from "@opal/layouts";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";
import type {
  CustomSkill,
  SkillAuthor,
} from "@/refresh-pages/admin/SkillsPage/interfaces";
import { summarizeVisibility } from "@/refresh-pages/admin/SkillsPage/helpers";

export type SkillCardSource = "builtin" | "owned" | "shared";

export interface SkillCardItem {
  id: string;
  name: string;
  description: string;
  author: SkillAuthor;
  source: SkillCardSource;
  // Built-in only
  available?: boolean;
  unavailable_reason?: string;
  // Custom skill passthrough (used for handler invocations)
  customSkill?: CustomSkill;
}

export interface SkillCardProps {
  item: SkillCardItem;
  onInspect?: (item: SkillCardItem) => void;
  onShare?: (skill: CustomSkill) => void;
  onReplaceBundle?: (skill: CustomSkill) => void;
  onDelete?: (skill: CustomSkill) => void;
}

export default function SkillCard({
  item,
  onInspect,
  onShare,
  onReplaceBundle,
  onDelete,
}: SkillCardProps) {
  const customSkill = item.customSkill;
  const isOwned = item.source === "owned";
  const isBuiltin = item.source === "builtin";

  const handleClick = useCallback(() => {
    onInspect?.(item);
  }, [onInspect, item]);

  const visibilitySummary =
    customSkill && !isBuiltin ? summarizeVisibility(customSkill) : null;

  return (
    <Interactive.Simple onClick={handleClick} group="group/SkillCard">
      <Card
        padding={0}
        gap={0}
        height="full"
        className="radial-00 hover:shadow-00"
      >
        <div className="flex self-stretch h-24">
          <CardItemLayout
            icon={SvgBlocks}
            title={item.name}
            description={item.description}
            rightChildren={
              isOwned && customSkill ? (
                <>
                  <IconButton
                    icon={SvgEdit}
                    tertiary
                    onClick={noProp(() => onReplaceBundle?.(customSkill))}
                    tooltip="Replace Bundle"
                    className="hidden group-hover/SkillCard:flex"
                  />
                  <IconButton
                    icon={SvgShare}
                    tertiary
                    onClick={noProp(() => onShare?.(customSkill))}
                    tooltip="Share Skill"
                    className="hidden group-hover/SkillCard:flex"
                  />
                  <IconButton
                    icon={SvgTrash}
                    tertiary
                    onClick={noProp(() => onDelete?.(customSkill))}
                    tooltip="Delete Skill"
                    className="hidden group-hover/SkillCard:flex"
                  />
                </>
              ) : null
            }
          />
        </div>

        <div className="bg-background-tint-01 p-1 flex flex-row items-center justify-between w-full">
          <div className="flex flex-col gap-1 py-1 px-2">
            <Content
              icon={SvgUser}
              title={item.author.email || item.author.name}
              sizePreset="secondary"
              variant="body"
              color="muted"
            />
          </div>
          <div className="p-0.5 pr-1.5">
            {isBuiltin ? (
              item.available ? (
                <Tag title="Built-in" color="blue" />
              ) : (
                <Tag
                  title={
                    item.unavailable_reason
                      ? `Unavailable — ${item.unavailable_reason}`
                      : "Unavailable"
                  }
                  color="amber"
                />
              )
            ) : visibilitySummary ? (
              <Tag title={visibilitySummary.label} color="gray" />
            ) : null}
          </div>
        </div>
      </Card>
    </Interactive.Simple>
  );
}
