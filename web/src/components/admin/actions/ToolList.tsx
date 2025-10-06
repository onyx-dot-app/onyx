import {
  MCPAuthenticationPerformer,
  MCPAuthenticationType,
} from "@/lib/tools/interfaces";
import Button from "@/refresh-components/buttons/Button";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import Text from "@/components/ui/text";
import { SearchIcon } from "lucide-react";
import { useMemo, useState, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import {
  MCPFormValues,
  MCPTool,
  ToolListProps,
  ToolListResponse,
} from "@/components/admin/actions/interfaces";
import { createMCPServer, attachMCPTools } from "@/lib/tools/edit";

const ITEMS_PER_PAGE = 10;

export function ToolList({
  values,
  verbRoot,
  serverId,
  setPopup,
  oauthConnected,
}: ToolListProps) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [listingTools, setListingTools] = useState(false);
  const [tools, setTools] = useState<MCPTool[]>([]);
  const [selectedTools, setSelectedTools] = useState<Set<string>>(new Set());
  const [searchTerm, setSearchTerm] = useState("");
  const [currentPage, setCurrentPage] = useState(1);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [currentServerId, setCurrentServerId] = useState<number | undefined>(
    serverId
  );

  // Auto-trigger tool listing when page loads with listing_tools=true query param
  useEffect(() => {
    if (
      searchParams.get("listing_tools") === "true" &&
      serverId &&
      values.name.trim() &&
      values.server_url.trim()
    ) {
      // Only auto-trigger for servers that have required form values and a serverId
      handleListActions(values);
    }
  }, [searchParams, serverId, values.name, values.server_url]);

  const handleListActions = async (values: MCPFormValues) => {
    // Check if OAuth needs connection first
    if (values.auth_type === MCPAuthenticationType.OAUTH && !oauthConnected) {
      setPopup({
        message: "Please connect OAuth first using the button above",
        type: "info",
      });
      return;
    }

    setListingTools(true);

    try {
      let newServerId = serverId;

      // For OAuth servers, skip server creation since it's already handled by the OAuth connection
      if (values.auth_type !== MCPAuthenticationType.OAUTH) {
        // Step 1: Create/update the MCP server with credentials
        const serverData = {
          name: values.name,
          description: values.description,
          server_url: values.server_url,
          auth_type: values.auth_type,
          auth_performer: values.auth_performer,
          api_token:
            values.auth_type === MCPAuthenticationType.API_TOKEN &&
            values.auth_performer === MCPAuthenticationPerformer.ADMIN
              ? values.api_token
              : undefined,
          auth_template:
            values.auth_performer === MCPAuthenticationPerformer.PER_USER
              ? values.auth_template
              : undefined,
          admin_credentials:
            values.auth_performer === MCPAuthenticationPerformer.PER_USER
              ? values.user_credentials || {}
              : undefined,
          oauth_client_id: undefined,
          oauth_client_secret: undefined,
          transport: values.transport,
          existing_server_id: serverId,
        };

        const { data: serverResult, error: serverError } =
          await createMCPServer(serverData);

        if (serverError || !serverResult) {
          setPopup({
            message: serverError || "Failed to create server",
            type: "error",
          });
          setListingTools(false);
          return;
        }

        // Update serverId for subsequent operations
        newServerId = serverResult.server_id;
        setCurrentServerId(newServerId);
      } else {
        // For OAuth servers, use the existing serverId
        if (!serverId) {
          setPopup({
            message: "Please reconnect to the OAuth server",
            type: "error",
          });
          setListingTools(false);
          return;
        }
        newServerId = serverId;
      }
      // Ensure URL reflects the created server and listing state to avoid duplicate creation
      // and set listing_tools=true so the tool list is shown
      router.replace(
        `/admin/actions/edit-mcp?server_id=${newServerId}&listing_tools=true`
      );

      // List available tools from the saved server
      const promises: Promise<Response>[] = [
        fetch(`/api/admin/mcp/server/${newServerId}/tools`, {
          method: "GET",
          headers: {
            "Content-Type": "application/json",
          },
        }),
        fetch(`/api/admin/mcp/server/${newServerId}/db-tools`, {
          method: "GET",
          headers: {
            "Content-Type": "application/json",
          },
        }),
      ];

      const responses = await Promise.all(promises);
      const toolsResp = responses[0];

      // Check if list-tools request failed
      if (!toolsResp?.ok) {
        let errorMessage = "Unknown error";
        if (toolsResp) {
          try {
            const errorJson = await toolsResp.clone().json();
            if (errorJson && typeof errorJson === "object") {
              errorMessage =
                errorJson.detail || errorJson.message || errorMessage;
            }
          } catch (_) {}
          if (errorMessage === "Unknown error") {
            try {
              const text = await toolsResp.text();
              if (text) errorMessage = text;
            } catch (_) {}
          }
        }
        setPopup({
          message: `Failed to list tools: ${errorMessage}`,
          type: "error",
        });
        setListingTools(false);
        return;
      }

      setCurrentPage(1);

      // Process available tools
      const toolsData: ToolListResponse = await toolsResp.json();
      setTools(toolsData.tools);

      // Pre-populate selected tools from existing database tools
      if (responses[1]?.ok) {
        const existingToolsData = await responses[1]?.json();
        const existingToolNames = new Set<string>(
          existingToolsData.tools.map((tool: any) => tool.name as string)
        );
        setSelectedTools(existingToolNames);
      } else {
        setSelectedTools(new Set());
      }

      // Tool list is already shown; nothing else to do
    } catch (error) {
      console.error("Error listing tools:", error);
      setPopup({
        message: "Error listing tools from MCP server",
        type: "error",
      });
    } finally {
      setListingTools(false);
    }
  };

  const handleCreateActions = async (values: MCPFormValues) => {
    if (selectedTools.size === 0) {
      setPopup({
        message: "Please select at least one tool",
        type: "error",
      });
      return;
    }

    if (!currentServerId) {
      setPopup({
        message: "Server not created yet. Please list actions first.",
        type: "error",
      });
      return;
    }

    setIsSubmitting(true);

    const { data, error } = await attachMCPTools({
      server_id: currentServerId,
      selected_tools: Array.from(selectedTools),
    });

    if (error) {
      setPopup({
        message: error,
        type: "error",
      });
    } else if (data) {
      const toolCount = data.updated_tools;
      const action = serverId ? "updated" : "created";
      setPopup({
        message: `Successfully ${action} ${toolCount} MCP tool${
          toolCount !== 1 ? "s" : ""
        }!`,
        type: "success",
      });
      // Clear query params and navigate to actions page
      router.push("/admin/actions");
    }

    setIsSubmitting(false);
  };

  // Filter tools based on search term
  const filteredTools = useMemo(() => {
    if (!searchTerm) return tools;
    const lowerSearchTerm = searchTerm.toLowerCase();
    return tools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(lowerSearchTerm) ||
        tool.description?.toLowerCase().includes(lowerSearchTerm) ||
        tool.displayName?.toLowerCase().includes(lowerSearchTerm)
    );
  }, [tools, searchTerm]);

  // Paginate filtered tools
  const paginatedTools = useMemo(() => {
    const startIndex = (currentPage - 1) * ITEMS_PER_PAGE;
    const endIndex = startIndex + ITEMS_PER_PAGE;
    return filteredTools.slice(startIndex, endIndex);
  }, [filteredTools, currentPage]);

  const totalPages = Math.ceil(filteredTools.length / ITEMS_PER_PAGE);

  const handleSelectAllFiltered = () => {
    const allFilteredToolNames = filteredTools.map((tool) => tool.name);
    setSelectedTools((prev) => {
      const newSet = new Set(prev);
      allFilteredToolNames.forEach((name) => newSet.add(name));
      return newSet;
    });
  };

  const handleDeselectAllFiltered = () => {
    const allFilteredToolNames = filteredTools.map((tool) => tool.name);
    setSelectedTools((prev) => {
      const newSet = new Set(prev);
      allFilteredToolNames.forEach((name) => newSet.delete(name));
      return newSet;
    });
  };

  const handleToggleTool = (toolName: string) => {
    setSelectedTools((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(toolName)) {
        newSet.delete(toolName);
      } else {
        newSet.add(toolName);
      }
      return newSet;
    });
  };

  const allFilteredSelected = filteredTools.every((tool) =>
    selectedTools.has(tool.name)
  );

  const someFilteredSelected = filteredTools.some((tool) =>
    selectedTools.has(tool.name)
  );

  const handleToggleAllFiltered = () => {
    if (allFilteredSelected) {
      handleDeselectAllFiltered();
    } else {
      handleSelectAllFiltered();
    }
  };

  return listingTools || searchParams.get("listing_tools") !== "true" ? (
    <div className="flex gap-2">
      <Button
        onClick={() => handleListActions(values)}
        disabled={
          listingTools ||
          !values.name.trim() ||
          !values.server_url.trim() ||
          (values.auth_type === MCPAuthenticationType.OAUTH && !oauthConnected)
        }
      >
        {listingTools ? "Listing Actions..." : "List Actions"}
      </Button>
      <Button secondary onClick={() => router.push("/admin/actions")}>
        Cancel
      </Button>
    </div>
  ) : (
    <div className="space-y-4 w-full">
      <h3 className="text-lg font-medium">Available Tools</h3>

      {/* Search bar */}
      <div className="relative">
        <SearchIcon className="absolute left-3 top-1/2 transform -translate-y-1/2 text-gray-400" />
        <Input
          type="text"
          placeholder="Search tools..."
          value={searchTerm}
          onChange={(e) => {
            setSearchTerm(e.target.value);
            setCurrentPage(1);
          }}
          className="pl-10"
        />
      </div>

      {/* Tool list with header */}
      <div className="border rounded-lg w-full overflow-hidden relative">
        {/* Header row with select all checkbox */}
        <div className="flex items-center p-4 border-b bg-gray-50 dark:bg-gray-800 rounded-t-lg">
          <div className="w-6 flex-none mr-3">
            <Checkbox
              checked={allFilteredSelected}
              onCheckedChange={handleToggleAllFiltered}
              className="mt-0"
              data-state={
                allFilteredSelected
                  ? "checked"
                  : someFilteredSelected
                    ? "indeterminate"
                    : "unchecked"
              }
            />
          </div>
          <div className="flex-1 font-medium text-sm text-gray-700 dark:text-gray-300">
            {searchTerm
              ? `Select all ${filteredTools.length} filtered tools`
              : `Select all ${filteredTools.length} tools`}
          </div>
        </div>

        {/* Tool list */}
        <div className="p-4 space-y-2 w-full">
          {paginatedTools.length === 0 ? (
            <Text className="text-gray-500 text-center py-4">
              {searchTerm ? "No tools match your search" : "No tools available"}
            </Text>
          ) : (
            paginatedTools.map((tool) => (
              <div
                key={tool.name}
                className="flex items-start p-2 hover:bg-gray-50 dark:hover:bg-gray-700 rounded w-full"
              >
                <div className="w-6 flex-none mr-3 pt-1">
                  <Checkbox
                    checked={selectedTools.has(tool.name)}
                    onCheckedChange={() => handleToggleTool(tool.name)}
                    className="mt-0"
                  />
                </div>
                <div className="flex-1">
                  <div className="font-medium">
                    {tool.displayName || tool.name}
                  </div>
                  {tool.description && (
                    <div className="text-sm text-gray-600 dark:text-gray-400 mt-1">
                      {tool.description}
                    </div>
                  )}
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex justify-between items-center">
          <Text className="text-sm text-gray-600 dark:text-gray-400">
            Page {currentPage} of {totalPages} ({filteredTools.length} tools)
          </Text>
          <div className="flex gap-2 ml-4">
            <Button
              secondary
              onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
              disabled={currentPage === 1}
            >
              Previous
            </Button>
            <Button
              secondary
              onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
              disabled={currentPage === totalPages}
            >
              Next
            </Button>
          </div>
        </div>
      )}

      {/* Selected count */}
      <div className="pt-4">
        <Text className="text-sm text-gray-600 dark:text-gray-400">
          {selectedTools.size} tool
          {selectedTools.size !== 1 ? "s" : ""} selected
        </Text>
        {selectedTools.size > 0 && (
          <div className="mt-2">
            <div className="text-xs text-gray-500 dark:text-gray-500 mb-1">
              Selected tools:
            </div>
            <div className="max-w-xs overflow-hidden">
              <div className="flex flex-wrap gap-1 items-start">
                {Array.from(selectedTools).map((toolName) => (
                  <span
                    key={toolName}
                    className="inline-block px-2 py-1 text-xs bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 rounded whitespace-nowrap flex-shrink-0"
                  >
                    {toolName}
                  </span>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Action buttons */}
      <div className="flex justify-end gap-2 pt-4 border-t">
        <Button
          onClick={() => handleCreateActions(values)}
          disabled={selectedTools.size === 0 || isSubmitting}
        >
          {verbRoot + (isSubmitting ? "ing..." : "e MCP Server Actions")}
        </Button>
        <Button
          secondary
          onClick={() => {
            // Remove listing_tools query parameter when going back to form
            const currentUrl = new URL(window.location.href);
            currentUrl.searchParams.delete("listing_tools");
            router.replace(currentUrl.toString());
          }}
        >
          Back
        </Button>
      </div>
    </div>
  );
}
