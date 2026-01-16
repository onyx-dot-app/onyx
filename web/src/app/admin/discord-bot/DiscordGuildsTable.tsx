"use client";

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
import { SvgEdit, SvgServer } from "@opal/icons";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import { DiscordGuildConfig } from "@/app/admin/discord-bot/types";
import { deleteGuildConfig } from "@/app/admin/discord-bot/lib";
import { PopupSpec } from "@/components/admin/connectors/Popup";

interface Props {
  guilds: DiscordGuildConfig[];
  onRefresh: () => void;
  setPopup: (popup: PopupSpec) => void;
}

export function DiscordGuildsTable({ guilds, onRefresh, setPopup }: Props) {
  const router = useRouter();

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
              ) : guild.enabled ? (
                <Badge variant="success">Enabled</Badge>
              ) : (
                <Badge variant="destructive">Disabled</Badge>
              )}
            </TableCell>
            <TableCell>
              <DeleteButton onClick={() => handleDelete(guild.id)} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
