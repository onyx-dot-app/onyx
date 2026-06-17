"use client";

import { useCallback } from "react";
import { Button, Switch, Tag } from "@opal/components";
import { Content } from "@opal/layouts";
import { SvgBlocks, SvgTrash, SvgUploadCloud, SvgUser } from "@opal/icons";
import { CardItemLayout } from "@/layouts/general-layouts";
import { Interactive } from "@opal/core";
import { Card } from "@/refresh-components/cards";
import { useSettings } from "@/lib/settings/hooks";

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
  /** True when the skill is a personal skill owned by the current user. */
  is_personal?: boolean;
  /** Disabled skills render greyed out; owners can re-enable via the toggle. */
  enabled?: boolean;
}

export type SkillCardItem = BuiltinSkillCardItem | CustomSkillCardItem;

export interface SkillCardProps {
  item: SkillCardItem;
  onClick?: (item: SkillCardItem) => void;
  /** Shown for owned personal skills only. */
  onReplaceBundle?: (item: CustomSkillCardItem) => void;
  onDelete?: (item: CustomSkillCardItem) => void;
  onToggleEnabled?: (item: CustomSkillCardItem, enabled: boolean) => void;
  /** Disables the action controls while a mutation for any card is in flight. */
  busy?: boolean;
}

export default function SkillCard({
  item,
  onClick,
  onReplaceBundle,
  onDelete,
  onToggleEnabled,
  busy = false,
}: SkillCardProps) {
  const { appName } = useSettings();

  const handleClick = useCallback(() => {
    onClick?.(item);
  }, [onClick, item]);

  const authorTitle =
    item.source === "builtin" ? appName : item.author_email || appName;
  const isDisabled = item.source === "custom" && item.enabled === false;

  return (
    <Interactive.Simple onClick={handleClick} group="group/SkillCard">
      <Card
        padding={0}
        gap={0}
        height="full"
        className={
          isDisabled ? "radial-00 opacity-50" : "radial-00 hover:shadow-00"
        }
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
          <div className="p-0.5 pr-1.5 flex items-center gap-1">
            {item.source === "custom" && item.is_personal && (
              <div
                className="flex items-center gap-0.5"
                onClick={(event) => event.stopPropagation()}
              >
                {onToggleEnabled && (
                  <Switch
                    checked={item.enabled !== false}
                    disabled={busy}
                    onCheckedChange={(checked) =>
                      onToggleEnabled(item, checked)
                    }
                  />
                )}
                {onReplaceBundle && (
                  <Button
                    prominence="tertiary"
                    size="sm"
                    icon={SvgUploadCloud}
                    tooltip="Replace bundle"
                    disabled={busy}
                    onClick={() => onReplaceBundle(item)}
                  />
                )}
                {onDelete && (
                  <Button
                    prominence="tertiary"
                    variant="danger"
                    size="sm"
                    icon={SvgTrash}
                    tooltip="Delete skill"
                    disabled={busy}
                    onClick={() => onDelete(item)}
                  />
                )}
              </div>
            )}
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
            ) : item.is_personal ? (
              <Tag title="Personal" color="purple" />
            ) : (
              <Tag title="Custom" color="gray" />
            )}
          </div>
        </div>
      </Card>
    </Interactive.Simple>
  );
}
