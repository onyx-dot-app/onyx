"use client";

import { useState } from "react";
import { Switch } from "@opal/components";
import { toast } from "@opal/layouts";
import type { UserRow } from "@/views/admin/UsersPage/interfaces";
import { setUsersCraftAccess } from "./svc";

interface AccessCellProps {
  user: UserRow;
  defaultEnabled: boolean;
  onMutate: () => void;
}

/** Per-user effective-access toggle. A change away from the workspace
 * default stores an override; a change back to match it clears the
 * override (the user follows the default again). */
export default function AccessCell({
  user,
  defaultEnabled,
  onMutate,
}: AccessCellProps) {
  const [isUpdating, setIsUpdating] = useState(false);

  const effective = user.craft_enabled ?? defaultEnabled;

  const handleChange = async (checked: boolean) => {
    setIsUpdating(true);
    try {
      await setUsersCraftAccess(
        [user.email],
        checked === defaultEnabled ? null : checked
      );
      toast.success(
        checked ? "Craft enabled for user" : "Craft disabled for user"
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update Craft access"
      );
    } finally {
      setIsUpdating(false);
      onMutate();
    }
  };

  return (
    <Switch
      checked={effective}
      disabled={isUpdating}
      onCheckedChange={(checked) => {
        void handleChange(checked);
      }}
    />
  );
}
