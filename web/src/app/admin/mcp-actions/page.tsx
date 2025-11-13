"use client";

import MCPActionCard from "@/sections/actions/MCPActionCard";
import Image from "next/image";

export default function MCPActionsPage() {
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-6">MCP Actions Demo</h1>

      <div className="flex flex-col gap-4 max-w-4xl">
        <h2 className="text-xl font-semibold mt-6 mb-2">Connected State</h2>

        {/* Example with Jira - Connected */}
        <MCPActionCard
          status="connected"
          title="Jira MCP"
          description="Jira MCP server for accessing, creating, and updating tickets for the dev team."
          logo={
            <Image
              src="/Jira.svg"
              alt="Jira"
              width={52}
              height={18}
              className="object-contain"
            />
          }
          toolCount={12}
          onDisconnect={() => console.log("Disconnect Jira")}
          onManage={() => console.log("Manage Jira")}
          onViewTools={() => console.log("View Jira tools")}
        />

        {/* Example with Slack - Connected */}
        <MCPActionCard
          status="connected"
          title="Slack MCP"
          description="Slack MCP server for sending messages, reading channels, and managing workspace."
          logo={
            <Image
              src="/Slack.png"
              alt="Slack"
              width={52}
              height={18}
              className="object-contain"
            />
          }
          toolCount={8}
          onDisconnect={() => console.log("Disconnect Slack")}
          onManage={() => console.log("Manage Slack")}
          onViewTools={() => console.log("View Slack tools")}
        />

        <h2 className="text-xl font-semibold mt-8 mb-2">Pending State</h2>

        {/* Example with Zapier - Pending */}
        <MCPActionCard
          status="pending"
          title="Zapier MCP"
          description="Test Zapier MCP server"
          onEdit={() => console.log("Edit Zapier")}
          onDelete={() => console.log("Delete Zapier")}
          onManage={() => console.log("Manage Zapier")}
          onAuthenticate={() => console.log("Authenticate Zapier")}
        />

        {/* Example with GitHub - Pending */}
        <MCPActionCard
          status="pending"
          title="GitHub MCP"
          description="GitHub MCP server for managing repositories, issues, and pull requests."
          onEdit={() => console.log("Edit GitHub")}
          onDelete={() => console.log("Delete GitHub")}
          onManage={() => console.log("Manage GitHub")}
          onAuthenticate={() => console.log("Authenticate GitHub")}
        />

        <h2 className="text-xl font-semibold mt-8 mb-2">Disconnected State</h2>

        {/* Example with Linear - Disconnected */}
        <MCPActionCard
          status="disconnected"
          title="Linear MCP"
          description="Linear MCP server for project management and issue tracking."
          onDelete={() => console.log("Delete Linear")}
          onManage={() => console.log("Manage Linear")}
          onReconnect={() => console.log("Reconnect Linear")}
        />

        {/* Example with Notion - Disconnected */}
        <MCPActionCard
          status="disconnected"
          title="Notion MCP"
          description="Notion MCP server for accessing and managing workspaces, databases, and pages."
          onDelete={() => console.log("Delete Notion")}
          onManage={() => console.log("Manage Notion")}
          onReconnect={() => console.log("Reconnect Notion")}
        />
      </div>
    </div>
  );
}
