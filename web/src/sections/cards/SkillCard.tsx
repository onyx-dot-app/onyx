"use client";

import { useCallback } from "react";
import { Tag } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgBlocks, SvgUser } from "@opal/icons";
import { CardItemLayout } from "@/layouts/general-layouts";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";
import { useSettingsContext } from "@/providers/SettingsProvider";

export type SkillCardSource = "builtin" | "custom";

interface SkillCardItemBase {
  id: string;
  name: string;
  description: string;
}

export interface BuiltinSkillCardItem extends SkillCardItemBase {
  source: "builtin";
  is_available: boolean;
  unavailable_reason?: string | null;
}

export interface CustomSkillCardItem extends SkillCardItemBase {
  source: "custom";
  author_email?: string | null;
}

export type SkillCardItem = BuiltinSkillCardItem | CustomSkillCardItem;

export interface SkillCardProps {
  item: SkillCardItem;
  onClick?: (item: SkillCardItem) => void;
}

export default function SkillCard({ item, onClick }: SkillCardProps) {
  const { enterpriseSettings } = useSettingsContext();
  const appName = enterpriseSettings?.application_name || "Onyx";

  const handleClick = useCallback(() => {
    onClick?.(item);
  }, [onClick, item]);

  const authorTitle =
    item.source === "builtin" ? appName : item.author_email || appName;

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
          />
        </div>

        <div className="bg-background-tint-01 p-1 flex flex-row items-center justify-between w-full">
          <div className="py-1 px-2 min-w-0 flex-1">
            <Content
              icon={SvgUser}
              title={authorTitle}
              sizePreset="secondary"
              variant="body"
              color="muted"
            />
          </div>
          <div className="p-0.5 pr-1.5">
            {item.source === "builtin" ? (
              item.is_available ? (
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
            ) : (
              <Tag title="Custom" color="gray" />
            )}
          </div>
        </div>
      </Card>
    </Interactive.Simple>
  );
}
