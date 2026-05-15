"use client";

import { useState } from "react";
import { Button, Popover, PopoverMenu } from "@opal/components";
import {
  SvgEdit,
  SvgEye,
  SvgEyeOff,
  SvgGlobe,
  SvgInfo,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
  SvgUploadCloud,
} from "@opal/icons";
import LineItem from "@/refresh-components/buttons/LineItem";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CustomSkillRowActionsProps {
  skill: CustomSkill;
  /** True on /admin/skills, false on /craft/v1/skills (user view). */
  adminMode: boolean;
  onOpen: () => void;
  onShare: () => void;
  onReplaceBundle: () => void;
  onToggleEnabled: () => void;
  onDelete: () => void;
  onPromote: () => void;
  onDemote: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CustomSkillRowActions({
  skill,
  adminMode,
  onOpen,
  onShare,
  onReplaceBundle,
  onToggleEnabled,
  onDelete,
  onPromote,
  onDemote,
}: CustomSkillRowActionsProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);

  const isOrgWide = skill.visibility === "org_wide";
  const showPromote = adminMode && !isOrgWide;
  const showDemote = adminMode && isOrgWide && skill.promoted_by_admin;

  return (
    <div className="flex items-center gap-0.5">
      <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
        <Button
          prominence="tertiary"
          icon={SvgInfo}
          tooltip="Inspect skill"
          onClick={onOpen}
        />
      </div>
      <div className="opacity-0 group-hover/row:opacity-100 transition-opacity">
        <Button
          prominence="tertiary"
          icon={SvgShare}
          tooltip="Share / set visibility"
          onClick={onShare}
        />
      </div>

      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <div
          className={cn(
            !popoverOpen &&
              "opacity-0 group-hover/row:opacity-100 transition-opacity"
          )}
        >
          <Popover.Trigger asChild>
            <Button prominence="tertiary" icon={SvgMoreHorizontal} />
          </Popover.Trigger>
        </div>
        <Popover.Content align="end" width="sm">
          <PopoverMenu>
            {[
              <LineItem
                key="open"
                icon={SvgInfo}
                onClick={() => {
                  setPopoverOpen(false);
                  onOpen();
                }}
              >
                Inspect
              </LineItem>,
              <LineItem
                key="share"
                icon={SvgShare}
                onClick={() => {
                  setPopoverOpen(false);
                  onShare();
                }}
              >
                Edit visibility
              </LineItem>,
              <LineItem
                key="replace"
                icon={SvgUploadCloud}
                onClick={() => {
                  setPopoverOpen(false);
                  onReplaceBundle();
                }}
              >
                Replace bundle
              </LineItem>,
              <LineItem
                key="edit-meta"
                icon={SvgEdit}
                onClick={() => {
                  setPopoverOpen(false);
                  onOpen();
                }}
              >
                Edit metadata
              </LineItem>,
              showPromote ? (
                <LineItem
                  key="promote"
                  icon={SvgGlobe}
                  onClick={() => {
                    setPopoverOpen(false);
                    onPromote();
                  }}
                >
                  Promote to org-wide
                </LineItem>
              ) : undefined,
              showDemote ? (
                <LineItem
                  key="demote"
                  icon={SvgGlobe}
                  onClick={() => {
                    setPopoverOpen(false);
                    onDemote();
                  }}
                >
                  Demote from org-wide
                </LineItem>
              ) : undefined,
              <LineItem
                key="enabled"
                icon={skill.enabled ? SvgEyeOff : SvgEye}
                onClick={() => {
                  setPopoverOpen(false);
                  onToggleEnabled();
                }}
              >
                {skill.enabled ? "Disable" : "Re-enable"}
              </LineItem>,
              <LineItem
                key="delete"
                icon={SvgTrash}
                danger
                onClick={() => {
                  setPopoverOpen(false);
                  onDelete();
                }}
              >
                Delete
              </LineItem>,
            ]}
          </PopoverMenu>
        </Popover.Content>
      </Popover>
    </div>
  );
}
