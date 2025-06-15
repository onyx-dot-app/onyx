import { TeamsChannelConfigForm } from "../../../TeamsChannelConfigForm";
import { useTeamsChannelConfigsByBot } from "../../../hooks";
import { notFound } from "next/navigation";

interface TeamsBotChannelConfigPageProps {
  params: {
    botId: string;
    channelId: string;
  };
}

export default function TeamsBotChannelConfigPage({
  params,
}: TeamsBotChannelConfigPageProps) {
  const { data: channelConfigs, error, isLoading } = useTeamsChannelConfigsByBot(params.botId);

  if (error) {
    return <div>Error loading channel configuration: {error.message}</div>;
  }

  if (isLoading) {
    return <div>Loading...</div>;
  }

  const config = channelConfigs?.find((c) => c.id === params.channelId);
  if (!config) {
    notFound();
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Edit Channel Configuration</h1>
      <div className="max-w-2xl mx-auto">
        <TeamsChannelConfigForm botId={params.botId} initialConfig={config} />
      </div>
    </div>
  );
} 