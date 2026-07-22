"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { MCPServer, ToolSnapshot } from "@/lib/tools/interfaces";
import { updateMCPServer } from "@/lib/tools/mcpService";
import IntegrationEditorModal from "@/app/craft/v1/apps/admin/IntegrationEditorModal";
import type { EndpointPolicy } from "@/app/craft/v1/apps/registry";

interface McpServerPolicyModalProps {
  onClose: () => void;
  onSaved: () => void;
  server: MCPServer;
}

/** Edit dialog for an MCP server's Craft tool policies: maps the server's
 * enabled tools into the shared editor. Server config itself (URL, auth, tool
 * refresh) lives on the MCP actions page. */
export default function McpServerPolicyModal({
  onClose,
  onSaved,
  server,
}: McpServerPolicyModalProps) {
  const { data: toolSnapshots } = useSWR<ToolSnapshot[]>(
    SWR_KEYS.adminMcpServerToolSnapshots(server.id),
    errorHandlingFetcher
  );
  const enabledTools = toolSnapshots?.filter((tool) => tool.enabled);

  async function save(
    _values: Record<string, string>,
    policies: Record<string, EndpointPolicy>
  ) {
    // Send the full map; the backend drops default (ASK) entries so the stored
    // set stays sparse regardless of which client wrote it.
    await updateMCPServer(server.id, { tool_policies: policies });
    onSaved();
  }

  return (
    <IntegrationEditorModal
      onClose={onClose}
      title={`Edit ${server.name}`}
      description="Configure what the Craft agent may do with this MCP server's tools."
      fields={[]}
      initialFieldValues={{}}
      // Policies are keyed by the tool's raw name (what the backend validates
      // against), not its display name. Stored overrides are sparse — unlisted
      // tools fall back to the per-item default of ASK.
      policyItems={enabledTools?.map((tool) => ({
        id: tool.name,
        name: tool.display_name || tool.name,
        description: tool.description,
        defaultPolicy: "ASK",
      }))}
      initialPolicies={{ ...server.tool_policies }}
      emptyPoliciesMessage="No enabled tools on this server. Enable tools on the MCP actions page first."
      saveLabel="Save"
      onSave={save}
    />
  );
}
