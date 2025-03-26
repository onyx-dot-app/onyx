import { TeamsBotTable } from "./TeamsBotTable";
import { TeamsBotCreationForm } from "./TeamsBotCreationForm";
import { useTeamsBots } from "./hooks";
import { Button } from "@/components/ui/button";
import { useState } from "react";

export default function TeamsBotsPage() {
  const { data: teamsBots, error, isLoading } = useTeamsBots();
  const [showCreateForm, setShowCreateForm] = useState(false);

  if (error) {
    return <div>Error loading Teams bots: {error.message}</div>;
  }

  if (isLoading) {
    return <div>Loading...</div>;
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-center">
        <h1 className="text-2xl font-bold">Teams Bots</h1>
        <Button onClick={() => setShowCreateForm(!showCreateForm)}>
          {showCreateForm ? "Cancel" : "Create Teams Bot"}
        </Button>
      </div>

      {showCreateForm ? (
        <div className="max-w-2xl mx-auto">
          <TeamsBotCreationForm />
        </div>
      ) : (
        <TeamsBotTable teamsBots={teamsBots || []} />
      )}
    </div>
  );
} 