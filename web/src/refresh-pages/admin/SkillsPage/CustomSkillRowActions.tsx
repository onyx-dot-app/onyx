"use client";

import { useState } from "react";
import { Button, Popover, PopoverMenu } from "@opal/components";
import {
  SvgEye,
  SvgEyeOff,
  SvgGlobe,
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
  onShare: () => void;
  onPromote: () => void;
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
  onPromote,
  onReplaceBundle,
  onToggleEnabled,
  onDelete,
}: CustomSkillRowActionsProps) {
  const [popoverOpen, setPopoverOpen] = useState(false);

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
              ...(skill.is_personal
                ? [
                    <LineItem
                      key="promote"
                      icon={SvgGlobe}
                      onClick={() => {
                        setPopoverOpen(false);
                        onPromote();
                      }}
                    >
                      Promote to organization
                    </LineItem>,
                  ]
                : []),
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
