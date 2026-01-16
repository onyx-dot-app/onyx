"use client";

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Switch from "@/refresh-components/inputs/Switch";
import EmptyMessage from "@/refresh-components/EmptyMessage";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";
import {
  DiscordChannelConfig,
  DiscordChannelType,
} from "@/app/admin/discord-bot/types";
import { SvgHash, SvgBubbleText, SvgLock } from "@opal/icons";
import { IconProps } from "@opal/types";

function getChannelIcon(
  channelType: DiscordChannelType,
  isPrivate: boolean = false
): React.ComponentType<IconProps> {
  // TODO: Need different icon for private channel vs private forum
  if (isPrivate) {
    return SvgLock;
  }
  switch (channelType) {
    case "forum":
      return SvgBubbleText;
    case "text":
    default:
      return SvgHash;
  }
}

interface Props {
  channels: DiscordChannelConfig[];
  onChannelUpdate: (
    channelId: number,
    field: "enabled" | "require_bot_invocation" | "thread_only_mode",
    value: boolean
  ) => void;
  disabled?: boolean;
}

export function DiscordChannelsTable({
  channels,
  onChannelUpdate,
  disabled = false,
}: Props) {
  if (channels.length === 0) {
    return (
      <EmptyMessage
        title="No channels configured"
        description="Run !sync-channels in Discord to add channels."
      />
    );
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Channel</TableHead>
          <TableHead>Enabled</TableHead>
          <TableHead>Require @mention</TableHead>
          <TableHead>Thread Only Mode</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {channels.map((channel) => {
          const ChannelIcon = getChannelIcon(
            channel.channel_type,
            channel.is_private
          );
          return (
            <TableRow key={channel.id}>
              <TableCell>
                <Section
                  flexDirection="row"
                  justifyContent="start"
                  gap={0.5}
                  fit
                >
                  <ChannelIcon width={16} height={16} />
                  <Text text04 mainUiBody>
                    {channel.channel_name}
                  </Text>
                </Section>
              </TableCell>
              <TableCell>
                <Switch
                  checked={channel.enabled}
                  onCheckedChange={(checked) =>
                    onChannelUpdate(channel.id, "enabled", checked)
                  }
                  disabled={disabled}
                />
              </TableCell>
              <TableCell>
                <Switch
                  checked={channel.require_bot_invocation}
                  onCheckedChange={(checked) =>
                    onChannelUpdate(
                      channel.id,
                      "require_bot_invocation",
                      checked
                    )
                  }
                  disabled={disabled}
                />
              </TableCell>
              <TableCell>
                {channel.channel_type !== "forum" && (
                  <Switch
                    checked={channel.thread_only_mode}
                    onCheckedChange={(checked) =>
                      onChannelUpdate(channel.id, "thread_only_mode", checked)
                    }
                    disabled={disabled}
                  />
                )}
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
