"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { ToolSnapshot, MCPServer } from "@/lib/tools/interfaces";
import { useRouter } from "next/navigation";
import { usePopup } from "@/components/admin/connectors/Popup";
import {
  FiCheckCircle,
  FiCode,
  FiEdit2,
  FiServer,
  FiXCircle,
} from "react-icons/fi";
import { TrashIcon } from "@/components/icons/icons";
import { deleteCustomTool, deleteMCPServer } from "@/lib/tools/edit";
import { TableHeader } from "@/components/ui/table";

export function ActionsTable({
  tools,
  mcpServers = [],
}: {
  tools: ToolSnapshot[];
  mcpServers?: MCPServer[];
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const sortedTools = [...tools];
  sortedTools.sort((a, b) => a.id - b.id);

  const sortedMcpServers = [...mcpServers];
  sortedMcpServers.sort((a, b) => a.id - b.id);

  return (
    <div>
      {popup}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Creation Method</TableHead>
            <TableHead>Delete</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {/* Render MCP Servers first */}
          {sortedMcpServers.map((server) => (
            <TableRow key={`mcp-${server.id}`}>
              <TableCell>
                <div className="flex">
                  <FiEdit2
                    className="mr-1 my-auto cursor-pointer"
                    onClick={() => {
                      router.push(
                        `/admin/actions/edit-mcp?server_id=${server.id}`
                      );
                    }}
                  />
                  <p className="text font-medium whitespace-normal break-none">
                    {server.name}
                  </p>
                </div>
              </TableCell>
              <TableCell className="whitespace-normal break-all max-w-2xl">
                MCP Server - {server.server_url}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <span>
                  <FiServer className="inline-block mr-1 my-auto" />
                  MCP Server
                </span>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <div className="flex">
                  <div className="my-auto">
                    <div
                      className="hover:bg-accent-background-hovered rounded p-1 cursor-pointer"
                      onClick={async () => {
                        const confirmDelete = window.confirm(
                          "Delete this MCP server and all its tools and configs? This cannot be undone."
                        );
                        if (!confirmDelete) return;
                        const response = await deleteMCPServer(server.id);
                        if (response.data?.success) {
                          router.refresh();
                        } else {
                          setPopup({
                            message: `Failed to delete MCP server - ${response.error}`,
                            type: "error",
                          });
                        }
                      }}
                    >
                      <TrashIcon />
                    </div>
                  </div>
                </div>
              </TableCell>
            </TableRow>
          ))}

          {/* Render regular tools */}
          {sortedTools.map((tool) => (
            <TableRow key={`tool-${tool.id}`}>
              <TableCell>
                <div className="flex">
                  {tool.in_code_tool_id === null && (
                    <FiEdit2
                      className="mr-1 my-auto cursor-pointer"
                      onClick={() => {
                        router.push(
                          `/admin/actions/edit/${tool.id}?u=${Date.now()}`
                        );
                      }}
                    />
                  )}
                  <p className="text font-medium whitespace-normal break-none">
                    {tool.name}
                  </p>
                </div>
              </TableCell>
              <TableCell className="whitespace-normal break-all max-w-2xl">
                {tool.description}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                {tool.in_code_tool_id === null ? (
                  <span>
                    <FiCode className="inline-block mr-1 my-auto" />
                    OpenAPI
                  </span>
                ) : (
                  <span>
                    <FiCheckCircle className="inline-block mr-1 my-auto" />
                    Built In
                  </span>
                )}
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <div className="flex">
                  {tool.in_code_tool_id === null ? (
                    <div className="my-auto">
                      <div
                        className="hover:bg-accent-background-hovered rounded p-1 cursor-pointer"
                        onClick={async () => {
                          const response = await deleteCustomTool(tool.id);
                          if (response.data) {
                            router.refresh();
                          } else {
                            setPopup({
                              message: `Failed to delete tool - ${response.error}`,
                              type: "error",
                            });
                          }
                        }}
                      >
                        <TrashIcon />
                      </div>
                    </div>
                  ) : (
                    "-"
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
