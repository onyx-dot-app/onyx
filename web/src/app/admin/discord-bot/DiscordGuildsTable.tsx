"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
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
import { Button } from "@opal/components";
import { Switch } from "@opal/components";
import { SvgEdit, SvgServer } from "@opal/icons";
import { EmptyMessageCard } from "@opal/components";
import { DiscordGuildConfig } from "@/app/admin/discord-bot/types";
import {
  deleteGuildConfig,
  updateGuildConfig,
} from "@/app/admin/discord-bot/lib";
import { toast } from "@opal/layouts";
import { ConfirmEntityModal } from "@/sections/modals/ConfirmEntityModal";

interface Props {
  guilds: DiscordGuildConfig[];
  onRefresh: () => void;
}

export function DiscordGuildsTable({ guilds, onRefresh }: Props) {
  const t = useTranslations("admin.discordBot");
  const locale = useLocale();
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
      toast.success(t("guilds.deleted.toast"));
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("guilds.deleteError.toast")
      );
    } finally {
      setGuildToDelete(null);
    }
  };

  const handleToggleEnabled = async (guild: DiscordGuildConfig) => {
    if (!guild.guild_id) {
      toast.error(t("guilds.notRegistered.toast"));
      return;
    }

    setUpdatingGuildIds((prev) => new Set(prev).add(guild.id));
    try {
      await updateGuildConfig(guild.id, {
        enabled: !guild.enabled,
        default_persona_id: guild.default_persona_id,
      });
      onRefresh();
      toast.success(
        !guild.enabled ? t("guilds.enabled.toast") : t("guilds.disabled.toast")
      );
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("guilds.updateError.toast")
      );
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
      <EmptyMessageCard
        sizePreset="main-ui"
        icon={SvgServer}
        title={t("guilds.empty.title")}
        description={t("guilds.empty.description")}
      />
    );
  }

  return (
    <>
      {guildToDelete && (
        <ConfirmEntityModal
          danger
          entityType={t("guilds.deleteModal.entityType")}
          entityName={
            guildToDelete.guild_name ||
            t("guilds.fallbackName", { id: guildToDelete.id })
          }
          onClose={() => setGuildToDelete(null)}
          onSubmit={() => handleDelete(guildToDelete.id)}
          additionalDetails={t("guilds.deleteModal.additionalDetails")}
        />
      )}
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("guilds.table.server.header")}</TableHead>
            <TableHead>{t("guilds.table.status.header")}</TableHead>
            <TableHead>{t("guilds.table.registered.header")}</TableHead>
            <TableHead>{t("guilds.table.enabled.header")}</TableHead>
            <TableHead>{t("guilds.table.actions.header")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {guilds.map((guild) => (
            <TableRow key={guild.id}>
              <TableCell>
                <Button
                  disabled={!guild.guild_id}
                  prominence="internal"
                  onClick={() => router.push(`/admin/discord-bot/${guild.id}`)}
                  icon={SvgEdit}
                >
                  {guild.guild_name ||
                    t("guilds.fallbackName", { id: guild.id })}
                </Button>
              </TableCell>
              <TableCell>
                {guild.guild_id ? (
                  <Badge variant="success">
                    {t("guilds.registered.badge")}
                  </Badge>
                ) : (
                  <Badge variant="secondary">{t("guilds.pending.badge")}</Badge>
                )}
              </TableCell>
              <TableCell>
                {guild.registered_at
                  ? new Date(guild.registered_at).toLocaleDateString(locale)
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
