"use client";

import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { useRouter } from "next/navigation";
import { usePopup } from "@/components/admin/connectors/Popup";
import { FiCheckCircle, FiEdit2, FiXCircle } from "react-icons/fi";
import { TrashIcon } from "@/components/icons/icons";
import { deleteCustomTool } from "@/lib/tools/edit";
import { TableHeader } from "@/components/ui/table";

export function ToolsTable({ tools }: { tools: ToolSnapshot[] }) {
  const router = useRouter();
  const { popup, setPopup } = usePopup();

  const sortedTools = [...tools];
  sortedTools.sort((a, b) => a.id - b.id);

  return (
    <div>
      {popup}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Description</TableHead>
            <TableHead>Built In?</TableHead>
            <TableHead>Delete</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {sortedTools.map((tool) => (
            <TableRow key={tool.id.toString()}>
              <TableCell>
                <div className="flex">
                  {tool.in_code_tool_id === null && (
                    <FiEdit2
                      className="mr-1 my-auto cursor-pointer"
                      onClick={() =>
                        router.push(
                          `/admin/tools/edit/${tool.id}?u=${Date.now()}`
                        )
                      }
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
                    <FiXCircle className="inline-block mr-1 my-auto" />
                    No
                  </span>
                ) : (
                  <span>
                    <FiCheckCircle className="inline-block mr-1 my-auto" />
                    Yes
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
