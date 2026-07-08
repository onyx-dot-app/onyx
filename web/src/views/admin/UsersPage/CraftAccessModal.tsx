"use client";

import { useMemo, useState } from "react";
import { Button, Switch } from "@opal/components";
import { SvgDevKit, SvgXCircle } from "@opal/icons";
import { InputTypeIn } from "@opal/components";
import Modal from "@/refresh-components/Modal";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useSettings } from "@/lib/settings/hooks";
import { toSettings } from "@/lib/settings/types";
import { updateAdminSettings } from "@/lib/settings/svc";
import useAdminUsers from "@/hooks/useAdminUsers";
import { setUsersCraftAccess } from "./svc";
import type { UserRow } from "./interfaces";

const MAX_CANDIDATE_RESULTS = 5;

interface CraftAccessModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * The workspace Craft-access policy in one place: the default for all users,
 * plus the per-user exceptions (overrides) as a managed list.
 */
export default function CraftAccessModal({
  open,
  onOpenChange,
}: CraftAccessModalProps) {
  const settings = useSettings();
  const { users, refresh } = useAdminUsers();
  const [search, setSearch] = useState("");
  const [isSaving, setIsSaving] = useState(false);

  const defaultEnabled = settings?.craft_default_enabled !== false;

  const exceptions = useMemo(
    () => users.filter((u) => u.id !== null && u.craft_enabled !== null),
    [users]
  );

  const candidates = useMemo(() => {
    const term = search.trim().toLowerCase();
    if (!term) return [];
    return users
      .filter(
        (u) =>
          u.id !== null &&
          u.craft_enabled === null &&
          (u.email.toLowerCase().includes(term) ||
            (u.personal_name ?? "").toLowerCase().includes(term))
      )
      .slice(0, MAX_CANDIDATE_RESULTS);
  }, [users, search]);

  async function setDefault(checked: boolean) {
    if (!settings) return;
    setIsSaving(true);
    try {
      await updateAdminSettings({
        ...toSettings(settings),
        craft_default_enabled: checked,
      });
      await mutate(SWR_KEYS.settings);
      toast.success(
        checked
          ? "Craft enabled by default for all users"
          : "Craft disabled by default for all users"
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update settings"
      );
    } finally {
      setIsSaving(false);
    }
  }

  async function applyOverride(user: UserRow, craftEnabled: boolean | null) {
    try {
      await setUsersCraftAccess([user.email], craftEnabled);
      refresh();
      setSearch("");
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to update Craft access"
      );
    }
  }

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgDevKit}
          title="Craft Access"
          onClose={() => onOpenChange(false)}
        />

        <Modal.Body>
          <div className="flex flex-col gap-4">
            <div className="flex items-center justify-between gap-2">
              <div className="flex flex-col">
                <Text as="span" mainUiBody text04>
                  Enable Craft for all users
                </Text>
                <Text as="span" secondaryBody text03>
                  Individual exceptions below always win over this default.
                </Text>
              </div>
              <Switch
                checked={defaultEnabled}
                disabled={isSaving}
                onCheckedChange={(checked) => {
                  void setDefault(checked);
                }}
              />
            </div>

            <div className="flex flex-col gap-2">
              <Text as="span" mainUiBody text04>
                Exceptions
              </Text>
              {exceptions.length === 0 && (
                <Text as="span" secondaryBody text03>
                  No exceptions — everyone follows the default.
                </Text>
              )}
              {exceptions.map((user) => (
                <div
                  key={user.id}
                  className="flex items-center justify-between gap-2"
                >
                  <Text as="span" secondaryBody text04>
                    {user.email}
                  </Text>
                  <div className="flex items-center gap-1">
                    <Text as="span" secondaryBody text03>
                      {user.craft_enabled ? "Enabled" : "Disabled"}
                    </Text>
                    <Button
                      icon={SvgXCircle}
                      prominence="tertiary"
                      size="xs"
                      tooltip="Remove exception (use default)"
                      aria-label="Remove exception"
                      onClick={() => {
                        void applyOverride(user, null);
                      }}
                    />
                  </div>
                </div>
              ))}
            </div>

            <div className="flex flex-col gap-2">
              <InputTypeIn
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={`Search users to ${
                  defaultEnabled ? "disable" : "enable"
                } Craft for...`}
                searchIcon
              />
              {candidates.map((user) => (
                <div
                  key={user.id}
                  className="flex items-center justify-between gap-2"
                >
                  <Text as="span" secondaryBody text04>
                    {user.email}
                  </Text>
                  <Button
                    prominence="secondary"
                    size="xs"
                    onClick={() => {
                      void applyOverride(user, !defaultEnabled);
                    }}
                  >
                    {defaultEnabled ? "Disable Craft" : "Enable Craft"}
                  </Button>
                </div>
              ))}
            </div>
          </div>
        </Modal.Body>
      </Modal.Content>
    </Modal>
  );
}
