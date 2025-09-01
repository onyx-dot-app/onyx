import { ActionsTable } from "./ActionTable";
import { ToolSnapshot, MCPServersResponse } from "@/lib/tools/interfaces";
import { Separator } from "@/components/ui/separator";
import Text from "@/components/ui/text";
import Title from "@/components/ui/title";
import { fetchSS } from "@/lib/utilsSS";
import { ErrorCallout } from "@/components/ErrorCallout";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CreateButton from "@/components/ui/createButton";
import { FiPlusCircle, FiHelpCircle } from "react-icons/fi";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export default async function Page() {
  // Fetch both tools and MCP servers
  const [toolResponse, mcpResponse] = await Promise.all([
    fetchSS("/tool"),
    fetchSS("/admin/mcp/servers"),
  ]);

  if (!toolResponse.ok) {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch tools - ${await toolResponse.text()}`}
      />
    );
  }

  const tools = (await toolResponse.json()) as ToolSnapshot[];

  // Filter out MCP tools from the regular tools list
  const nonMcpTools = tools.filter((tool) => !tool.mcp_server_id);

  let mcpServers: MCPServersResponse["mcp_servers"] = [];
  if (mcpResponse.ok) {
    try {
      const mcpData = (await mcpResponse.json()) as MCPServersResponse;
      mcpServers = mcpData.mcp_servers;
    } catch (error) {
      console.error("Error parsing MCP servers response:", error);
    }
  } else {
    return (
      <ErrorCallout
        errorTitle="Something went wrong :("
        errorMsg={`Failed to fetch MCP servers - ${await mcpResponse.text()}`}
      />
    );
  }

  return (
    <div className="mx-auto container">
      <AdminPageTitle
        icon={<ToolIcon size={32} className="my-auto" />}
        title="Actions"
      />

      <Text className="mb-2">
        Actions allow assistants to retrieve information or take actions.
      </Text>

      <div>
        <Separator />

        <Title>Create Actions</Title>
        <div className="flex gap-4 mt-2 items-center">
          <CreateButton
            href="/admin/actions/new"
            text="From OpenAPI schema"
            icon={<FiPlusCircle />}
          />
          <CreateButton
            href="/admin/actions/edit-mcp"
            text="From MCP server"
            icon={<FiPlusCircle />}
          />
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger>
                <FiHelpCircle className="h-4 w-4 text-subtle hover:text-emphasis cursor-help" />
              </TooltipTrigger>
              <TooltipContent>
                <p className="max-w-xs">
                  MCP (Model Context Protocol) servers provide structured ways
                  for AI models to interact with external systems and data
                  sources. They offer a standardized interface for tools and
                  resources.
                </p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>

        <Separator />

        <Title>Existing Actions</Title>
        <ActionsTable tools={nonMcpTools} mcpServers={mcpServers} />
      </div>
    </div>
  );
}
