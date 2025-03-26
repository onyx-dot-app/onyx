import { TeamsChannelConfigsTable } from "../../TeamsChannelConfigsTable";
import { TeamsChannelConfigForm } from "../../TeamsChannelConfigForm";
import { useTeamsChannelConfigsByBot } from "../../hooks";
import { Button } from "@/components/ui/button";
import { useState } from "react";

interface TeamsBotChannelsPageProps {
  params: {
    botId: string;
  };
}

export default function TeamsBotChannelsPage({ params }: TeamsBotChannelsPageProps) {
  const { data: channelConfigs, error, isLoading } = useTeamsChannelConfigsByBot(params.botId);
  const [showCreateForm, setShowCreateForm] = useState(false);

  if (error) {
    return <div>Error loading channel configurations: {error.message}</div>;
  }

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Channel Configurations</h1>
        <Button onClick={() => setShowCreateForm(!showCreateForm)}>
          {showCreateForm ? "Cancel" : "Create Channel Configuration"}
        </Button>
      </div>

      {showCreateForm ? (
        <div className="max-w-2xl mx-auto">
          <TeamsChannelConfigForm botId={params.botId} />
        </div>
      ) : (
        <TeamsChannelConfigsTable
          channelConfigs={channelConfigs || []}
          botId={params.botId}
        />
      )}
    </div>
  );
} 