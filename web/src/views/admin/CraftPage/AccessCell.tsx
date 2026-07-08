"use client";

import { useRef, useState } from "react";
import { OpenButton, Popover, Divider } from "@opal/components";
import { Disabled } from "@opal/core";
import {
  SvgCheck,
  SvgCheckCircle,
  SvgMinusCircle,
  SvgXCircle,
} from "@opal/icons";
import LineItem from "@/refresh-components/buttons/LineItem";
import { toast } from "@/hooks/useToast";
import type { UserRow } from "@/views/admin/UsersPage/interfaces";
import { setUsersCraftAccess } from "./svc";

interface AccessCellProps {
  user: UserRow;
  defaultEnabled: boolean;
  onMutate: () => void;
}

/** Per-row access control for an exception: Enabled / Disabled / Remove. */
export default function AccessCell({
  user,
  defaultEnabled,
  onMutate,
}: AccessCellProps) {
  const [isUpdating, setIsUpdating] = useState(false);
  const [open, setOpen] = useState(false);
  const isUpdatingRef = useRef(false);

  const enabled = user.craft_enabled === true;
  // An override matching the workspace default changes nothing today; it
  // only pins the user's access if the default flips.
  const noEffect = user.craft_enabled === defaultEnabled;

  const apply = async (craftEnabled: boolean | null, message: string) => {
    if (isUpdatingRef.current) return;
    isUpdatingRef.current = true;
    setIsUpdating(true);
    try {
      await setUsersCraftAccess([user.email], craftEnabled);
      toast.success(message);
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update Craft access"
      );
    } finally {
      setIsUpdating(false);
      isUpdatingRef.current = false;
      onMutate();
    }
  };

  const handleSelect = (craftEnabled: boolean | null, message: string) => {
    setOpen(false);
    if (craftEnabled === user.craft_enabled) return;
    void apply(craftEnabled, message);
  };

  return (
    <Disabled disabled={isUpdating}>
      <Popover open={open} onOpenChange={setOpen}>
        <Popover.Trigger asChild>
          <OpenButton
            icon={enabled ? SvgCheckCircle : SvgXCircle}
            variant="select-tinted"
            width="full"
            justifyContent="between"
            rounding="sm"
          >
            {(enabled ? "Enabled" : "Disabled") +
              (noEffect ? " · No effect" : "")}
          </OpenButton>
        </Popover.Trigger>
        <Popover.Content align="start">
          <div className="flex flex-col gap-1 p-1 min-w-[200px]">
            <LineItem
              icon={enabled ? SvgCheck : SvgCheckCircle}
              selected={enabled}
              onClick={() => handleSelect(true, "Craft enabled for user")}
            >
              Enabled
            </LineItem>
            <LineItem
              icon={!enabled ? SvgCheck : SvgXCircle}
              selected={!enabled}
              onClick={() => handleSelect(false, "Craft disabled for user")}
            >
              Disabled
            </LineItem>
            <Divider paddingPerpendicular="md" />
            <LineItem
              danger
              icon={SvgMinusCircle}
              onClick={() =>
                handleSelect(null, "Exception removed — user follows default")
              }
            >
              Remove Exception
            </LineItem>
          </div>
        </Popover.Content>
      </Popover>
    </Disabled>
  );
}
