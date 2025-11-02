import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { createTeamsChannelConfig } from "./lib";
import { TeamsChannelConfig } from "@/lib/types";

interface TeamsChannelConfigFormProps {
  botId: string;
  initialConfig?: TeamsChannelConfig;
}

export const TeamsChannelConfigForm = ({
  botId,
  initialConfig,
}: TeamsChannelConfigFormProps) => {
  const router = useRouter();
  const [channelName, setChannelName] = useState(initialConfig?.channel_name || "");
  const [channelId, setChannelId] = useState(initialConfig?.channel_id || "");
  const [enabled, setEnabled] = useState(initialConfig?.enabled || true);
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      await createTeamsChannelConfig(botId, {
        channel_name: channelName,
        channel_id: channelId,
        enabled,
      });
      router.push(`/admin/bots/teams/${botId}/channels`);
    } catch (error) {
      console.error("Failed to create channel configuration:", error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="channelName">Channel Name</Label>
        <Input
          id="channelName"
          value={channelName}
          onChange={(e) => setChannelName(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="channelId">Channel ID</Label>
        <Input
          id="channelId"
          value={channelId}
          onChange={(e) => setChannelId(e.target.value)}
          required
        />
      </div>
      <div className="flex items-center space-x-2">
        <Switch
          id="enabled"
          checked={enabled}
          onCheckedChange={setEnabled}
        />
        <Label htmlFor="enabled">Enabled</Label>
      </div>
      <Button type="submit" disabled={isLoading}>
        {isLoading ? "Creating..." : "Create Channel Configuration"}
      </Button>
    </form>
  );
}; 