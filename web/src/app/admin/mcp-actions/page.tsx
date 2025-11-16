"use client";

import MCPActionCard from "@/sections/actions/ActionCard";
import type { Tool } from "@/sections/actions/ToolsList";
import Image from "next/image";
import { useState } from "react";

export default function MCPActionsPage() {
  // Sample tools data for Jira
  const [jiraTools, setJiraTools] = useState<Tool[]>([
    {
      id: "get_ticket",
      name: "get_ticket",
      description: "Get Jira tickets in your team.",
      icon: (
        <Image
          src="/Jira.svg"
          alt="Jira"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: true,
      isEnabled: true,
    },
    {
      id: "create_ticket",
      name: "create_ticket",
      description: "Create a new ticket in Jira.",
      icon: (
        <Image
          src="/Jira.svg"
          alt="Jira"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: true,
      isEnabled: true,
    },
    {
      id: "update_ticket",
      name: "update_ticket",
      description: "Update details of an existing ticket in Jira.",
      icon: (
        <Image
          src="/Jira.svg"
          alt="Jira"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: true,
      isEnabled: true,
    },
    {
      id: "delete_ticket",
      name: "delete_ticket",
      description: "Delete an existing ticket in Jira.",
      icon: (
        <Image
          src="/Jira.svg"
          alt="Jira"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: true,
      isEnabled: false,
    },
    {
      id: "resolve_ticket",
      name: "resolve_ticket",
      description: "Resolve an existing ticket in Jira.",
      icon: (
        <Image
          src="/Jira.svg"
          alt="Jira"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: false,
      isEnabled: false,
    },
  ]);

  // Sample tools data for Slack
  const [slackTools, setSlackTools] = useState<Tool[]>([
    {
      id: "send_message",
      name: "send_message",
      description: "Send a message to a Slack channel.",
      icon: (
        <Image
          src="/Slack.png"
          alt="Slack"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: true,
      isEnabled: true,
    },
    {
      id: "read_channel",
      name: "read_channel",
      description: "Read messages from a Slack channel.",
      icon: (
        <Image
          src="/Slack.png"
          alt="Slack"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: true,
      isEnabled: true,
    },
    {
      id: "create_channel",
      name: "create_channel",
      description: "Create a new channel in Slack.",
      icon: (
        <Image
          src="/Slack.png"
          alt="Slack"
          width={16}
          height={16}
          className="object-contain"
        />
      ),
      isAvailable: false,
      isEnabled: false,
    },
  ]);

  const handleJiraToolToggle = (toolId: string, enabled: boolean) => {
    setJiraTools((prev) =>
      prev.map((tool) =>
        tool.id === toolId ? { ...tool, isEnabled: enabled } : tool
      )
    );
    console.log(`Jira tool ${toolId} toggled to ${enabled}`);
  };

  const handleSlackToolToggle = (toolId: string, enabled: boolean) => {
    setSlackTools((prev) =>
      prev.map((tool) =>
        tool.id === toolId ? { ...tool, isEnabled: enabled } : tool
      )
    );
    console.log(`Slack tool ${toolId} toggled to ${enabled}`);
  };

  const handleDisableAllJira = () => {
    setJiraTools((prev) => prev.map((tool) => ({ ...tool, isEnabled: false })));
    console.log("All Jira tools disabled");
  };

  const handleDisableAllSlack = () => {
    setSlackTools((prev) =>
      prev.map((tool) => ({ ...tool, isEnabled: false }))
    );
    console.log("All Slack tools disabled");
  };

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
          toolCount={jiraTools.length}
          tools={jiraTools}
          onDisconnect={() => console.log("Disconnect Jira")}
          onManage={() => console.log("Manage Jira")}
          onToolToggle={handleJiraToolToggle}
          onRefreshTools={() => console.log("Refresh Jira tools")}
          onDisableAllTools={handleDisableAllJira}
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
          toolCount={slackTools.length}
          tools={slackTools}
          onDisconnect={() => console.log("Disconnect Slack")}
          onManage={() => console.log("Manage Slack")}
          onToolToggle={handleSlackToolToggle}
          onRefreshTools={() => console.log("Refresh Slack tools")}
          onDisableAllTools={handleDisableAllSlack}
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
