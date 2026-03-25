"use client";

import { use } from "react";
import { useAgent } from "@/hooks/useAgents";
import AgentEditorPage from "@/refresh-pages/AgentEditorPage";
import ResourceErrorPage from "@/sections/error/ResourceErrorPage";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import * as AppLayouts from "@/layouts/app-layouts";

export interface PageProps {
  params: Promise<{ id: string }>;
}

export default function Page(props: PageProps) {
  const { id } = use(props.params);
  const agentId = parseInt(id);

  // Call hook unconditionally (passes null when ID is invalid)
  const { agent, isLoading, refresh } = useAgent(
    isNaN(agentId) ? null : agentId
  );

  if (isLoading) return <SimpleLoader />;

  if (isNaN(agentId) || !agent) {
    return (
      <ResourceErrorPage
        errorType="not_found"
        title="Agent not found"
        description="This agent doesn't exist or has been deleted."
        backHref="/app"
        backLabel="Start a new chat"
      />
    );
  }

  return (
    <AppLayouts.Root>
      <AgentEditorPage agent={agent} refreshAgent={refresh} />
    </AppLayouts.Root>
  );
}
