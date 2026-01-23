"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { DeleteButton } from "@/components/DeleteButton";
import Button from "@/refresh-components/buttons/Button";
import Switch from "@/refresh-components/inputs/Switch";
import { SvgEdit, SvgServer } from "@opal/icons";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { DiscordGuildConfig } from "@/app/admin/discord-bot/types";
import {
  deleteGuildConfig,
  updateGuildConfig,
} from "@/app/admin/discord-bot/lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";

interface Props {
  guilds: DiscordGuildConfig[];
  onRefresh: () => void;
  setPopup: (popup: PopupSpec) => void;
}

export function DiscordGuildsTable({ guilds, onRefresh, setPopup }: Props) {
  const router = useRouter();
  const [guildToDelete, setGuildToDelete] = useState<DiscordGuildConfig | null>(
    null
  );
  const [updatingGuildIds, setUpdatingGuildIds] = useState<Set<number>>(
    new Set()
  );

  const handleDelete = async (guildId: number) => {
    try {
      await deleteGuildConfig(guildId);
      onRefresh();
      setPopup({ type: "success", message: "Server configuration deleted" });
    } catch (err) {
      setPopup({
        type: "error",
        message:
          err instanceof Error ? err.message : "Failed to delete server config",
      });
    } finally {
      setGuildToDelete(null);
    }
  };

  const handleToggleEnabled = async (guild: DiscordGuildConfig) => {
    if (!guild.guild_id) {
      setPopup({
        type: "error",
        message: "Server must be registered before it can be enabled",
      });
      return;
    }

    setUpdatingGuildIds((prev) => new Set(prev).add(guild.id));
    try {
      await updateGuildConfig(guild.id, {
        enabled: !guild.enabled,
        default_persona_id: guild.default_persona_id,
      });
      onRefresh();
      setPopup({
        type: "success",
        message: `Server ${!guild.enabled ? "enabled" : "disabled"}`,
      });
    } catch (err) {
      setPopup({
        type: "error",
        message: err instanceof Error ? err.message : "Failed to update server",
      });
    } finally {
      setUpdatingGuildIds((prev) => {
        const next = new Set(prev);
        next.delete(guild.id);
        return next;
      });
    }
  };

  if (guilds.length === 0) {
    return (
      <EmptyMessage
        icon={SvgServer}
        title="No Discord servers configured yet"
        description="Create a server configuration to get started."
      />
    );
  }

  return (
    <>
      {guildToDelete && (
        <ConfirmEntityModal
          danger
          entityType="Discord server configuration"
          entityName={guildToDelete.guild_name || `Server #${guildToDelete.id}`}
          onClose={() => setGuildToDelete(null)}
          onSubmit={() => handleDelete(guildToDelete.id)}
          additionalDetails="This will remove all settings for this Discord server."
        />
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Server</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Registered</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {guilds.map((guild) => (
            <TableRow key={guild.id}>
              <TableCell>
                <Button
                  internal
                  disabled={!guild.guild_id}
                  onClick={() => router.push(`/admin/discord-bot/${guild.id}`)}
                  leftIcon={SvgEdit}
                >
                  {guild.guild_name || `Server #${guild.id}`}
                </Button>
              </TableCell>
              <TableCell>
                {guild.guild_id ? (
                  <Badge variant="success">Registered</Badge>
                ) : (
                  <Badge variant="secondary">Pending</Badge>
                )}
              </TableCell>
              <TableCell>
                {guild.registered_at
                  ? new Date(guild.registered_at).toLocaleDateString()
                  : "-"}
              </TableCell>
              <TableCell>
                {!guild.guild_id ? (
                  "-"
                ) : (
                  <Switch
                    checked={guild.enabled}
                    onCheckedChange={() => handleToggleEnabled(guild)}
                    disabled={updatingGuildIds.has(guild.id)}
                  />
                )}
              </TableCell>
              <TableCell>
                <DeleteButton onClick={() => setGuildToDelete(guild)} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </>
  );
}
