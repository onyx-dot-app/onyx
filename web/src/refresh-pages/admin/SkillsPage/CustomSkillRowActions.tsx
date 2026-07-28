"use client";

import { useState } from "react";
import { Button, Popover, PopoverMenu } from "@opal/components";
import {
  SvgEye,
  SvgEyeOff,
  SvgMoreHorizontal,
  SvgShare,
  SvgTrash,
  SvgUploadCloud,
} from "@opal/icons";
import LineItem from "@/refresh-components/buttons/LineItem";
import type { CustomSkill } from "@/refresh-pages/admin/SkillsPage/interfaces";
import { can } from "@/lib/permissions/resource-actions";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface CustomSkillRowActionsProps {
  skill: CustomSkill;
  onShare: () => void;
  onReplaceBundle: () => void;
  onToggleEnabled: () => void;
  onDelete: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function CustomSkillRowActions({
  skill,
  onShare,
  onReplaceBundle,
  onToggleEnabled,
  onDelete,
}: CustomSkillRowActionsProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);

  // Row affordances ride on the server-stamped map: edit gates replace/disable,
  // manage_access gates visibility grants, delete is admin-only.
  const canEdit = can(skill, "edit");
  const canManageAccess = can(skill, "manage_access");
  const canDelete = can(skill, "delete");
  const hasItems = canEdit || canManageAccess || canDelete;

  if (!hasItems) return null;

  return (
    <div className="flex items-center gap-0.5">
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
              canManageAccess ? (
                <LineItem
                  key="share"
                  icon={SvgShare}
                  onClick={() => {
                    setPopoverOpen(false);
                    onShare();
                  }}
                >
                  Edit visibility
                </LineItem>
              ) : undefined,
              canEdit ? (
                <LineItem
                  key="replace"
                  icon={SvgUploadCloud}
                  onClick={() => {
                    setPopoverOpen(false);
                    onReplaceBundle();
                  }}
                >
                  Replace bundle
                </LineItem>
              ) : undefined,
              canEdit ? (
                <LineItem
                  key="enabled"
                  icon={skill.enabled ? SvgEyeOff : SvgEye}
                  onClick={() => {
                    setPopoverOpen(false);
                    onToggleEnabled();
                  }}
                >
                  {skill.enabled ? "Disable" : "Re-enable"}
                </LineItem>
              ) : undefined,
              canDelete ? (
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
                </LineItem>
              ) : undefined,
            ]}
          </PopoverMenu>
        </Popover.Content>
      </Popover>
    </div>
  );
}
