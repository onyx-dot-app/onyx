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
import SvgCheckCircle from "@/icons/check-circle";
import SvgCode from "@/icons/code";
import SvgEdit from "@/icons/edit";
import SvgServer from "@/icons/server";
import SvgTrash from "@/icons/trash";
import { deleteCustomTool, deleteMCPServer } from "@/lib/tools/edit";
import { TableHeader } from "@/components/ui/table";
import { useUser } from "@/components/user/UserProvider";
import { UserRole } from "@/lib/types";
import IconButton from "@/refresh-components/buttons/IconButton";
import Text from "@/refresh-components/texts/Text";

export function ActionsTable({
  tools,
  mcpServers = [],
}: {
  tools: ToolSnapshot[];
  mcpServers?: MCPServer[];
}) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();
  const { user } = useUser();

  const isAdmin = user?.role === UserRole.ADMIN;

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
                <div className="flex items-center gap-2">
                  {isAdmin || server.owner === user?.email ? (
                    <IconButton
                      icon={SvgEdit}
                      tertiary
                      onClick={() => {
                        router.push(
                          `/admin/actions/edit-mcp?server_id=${server.id}`
                        );
                      }}
                    />
                  ) : null}
                  <Text
                    mainUiBody
                    text04
                    className="whitespace-normal break-words"
                  >
                    {server.name}
                  </Text>
                </div>
              </TableCell>
              <TableCell className="whitespace-normal break-words max-w-2xl">
                <Text text03>{`MCP Server - ${server.server_url}`}</Text>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <div className="flex items-center gap-2">
                  <SvgServer
                    stroke="currentColor"
                    className="size-4 text-text-03"
                  />
                  <Text text03>MCP Server</Text>
                </div>
              </TableCell>
              <TableCell className="whitespace-nowrap">
                <div className="flex items-center">
                  {isAdmin || server.owner === user?.email ? (
                    <IconButton
                      icon={SvgTrash}
                      tertiary
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
                    />
                  ) : (
                    <Text text03>-</Text>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}

          {/* Render regular tools */}
          {sortedTools.map((tool) => {
            const isCustomTool = tool.in_code_tool_id === null;
            const canModifyTool =
              isCustomTool &&
              (isAdmin || (!!tool.user_id && tool.user_id === user?.id));

            return (
              <TableRow key={`tool-${tool.id}`}>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {canModifyTool && (
                      <IconButton
                        icon={SvgEdit}
                        tertiary
                        onClick={() => {
                          router.push(
                            `/admin/actions/edit/${tool.id}?u=${Date.now()}`
                          );
                        }}
                      />
                    )}
                    <Text
                      mainUiBody
                      text04
                      className="whitespace-normal break-words"
                    >
                      {tool.name}
                    </Text>
                  </div>
                </TableCell>
                <TableCell className="whitespace-normal break-words max-w-2xl">
                  <Text text03>{tool.description ?? ""}</Text>
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  {isCustomTool ? (
                    <div className="flex items-center gap-2">
                      <SvgCode
                        stroke="currentColor"
                        className="size-4 text-text-03"
                      />
                      <Text text03>OpenAPI</Text>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <SvgCheckCircle
                        stroke="currentColor"
                        className="size-4 text-text-03"
                      />
                      <Text text03>Built In</Text>
                    </div>
                  )}
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <div className="flex items-center">
                    {isCustomTool ? (
                      canModifyTool ? (
                        <IconButton
                          icon={SvgTrash}
                          tertiary
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
                        />
                      ) : (
                        <Text text03>-</Text>
                      )
                    ) : (
                      <Text text03>-</Text>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </div>
  );
}
