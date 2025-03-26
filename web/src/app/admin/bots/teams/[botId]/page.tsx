import { TeamsBotCreationForm } from "../TeamsBotCreationForm";
import { useTeamsBot } from "../hooks";
import { notFound } from "next/navigation";

interface TeamsBotEditPageProps {
  params: {
    botId: string;
  };
}

export default function TeamsBotEditPage({ params }: TeamsBotEditPageProps) {
  const { data: teamsBot, error, isLoading } = useTeamsBot(params.botId);

  if (error) {
    return <div>Error loading Teams bot: {error.message}</div>;
  }

  if (isLoading) {
    return <div>Loading...</div>;
  }

  if (!teamsBot) {
    notFound();
  }

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold">Edit Teams Bot</h1>
      <div className="max-w-2xl mx-auto">
        <TeamsBotCreationForm initialBot={teamsBot} />
      </div>
    </div>
  );
} 