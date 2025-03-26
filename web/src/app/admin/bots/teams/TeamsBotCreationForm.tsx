import { useState } from "react";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { createTeamsBot } from "./lib";
import { TeamsBotCreationRequest } from "@/lib/types";

export const TeamsBotCreationForm = () => {
  const router = useRouter();
  const [name, setName] = useState("");
  const [teamId, setTeamId] = useState("");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [clientId, setClientId] = useState("");
  const [clientSecret, setClientSecret] = useState("");
  const [tenantId, setTenantId] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);

    try {
      const request: TeamsBotCreationRequest = {
        name,
        team_id: teamId,
        webhook_url: webhookUrl,
        tokens: {
          client_id: clientId,
          client_secret: clientSecret,
          tenant_id: tenantId,
        },
      };

      await createTeamsBot(request);
      router.push("/admin/bots/teams");
    } catch (error) {
      console.error("Failed to create Teams bot:", error);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="name">Name</Label>
        <Input
          id="name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="teamId">Team ID</Label>
        <Input
          id="teamId"
          value={teamId}
          onChange={(e) => setTeamId(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="webhookUrl">Webhook URL</Label>
        <Input
          id="webhookUrl"
          value={webhookUrl}
          onChange={(e) => setWebhookUrl(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="clientId">Client ID</Label>
        <Input
          id="clientId"
          value={clientId}
          onChange={(e) => setClientId(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="clientSecret">Client Secret</Label>
        <Input
          id="clientSecret"
          type="password"
          value={clientSecret}
          onChange={(e) => setClientSecret(e.target.value)}
          required
        />
      </div>
      <div className="space-y-2">
        <Label htmlFor="tenantId">Tenant ID</Label>
        <Input
          id="tenantId"
          value={tenantId}
          onChange={(e) => setTenantId(e.target.value)}
          required
        />
      </div>
      <Button type="submit" disabled={isLoading}>
        {isLoading ? "Creating..." : "Create Teams Bot"}
      </Button>
    </form>
  );
}; 