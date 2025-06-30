"use client";
import i18n from "@/i18n/init";
import k from "./../../../i18n/keys";

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

export function ActionsTable({ tools }: { tools: ToolSnapshot[] }) {
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
            <TableHead>{i18n.t(k.NAME)}</TableHead>
            <TableHead>{i18n.t(k.DESCRIPTION)}</TableHead>
            <TableHead>{i18n.t(k.BUILT_IN)}</TableHead>
            <TableHead>{i18n.t(k.DELETE)}</TableHead>
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
                          `/admin/actions/edit/${tool.id}?u=${Date.now()}`
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
                    {i18n.t(k.NO)}
                  </span>
                ) : (
                  <span>
                    <FiCheckCircle className="inline-block mr-1 my-auto" />
                    {i18n.t(k.YES)}
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
                              message: `${i18n.t(k.FAILED_TO_DELETE_TOOL)} ${response.error
                                }`,

                              type: "error",
                            });
                          }
                        }}
                      >
                        <TrashIcon />
                      </div>
                    </div>
                  ) : (
                    i18n.t(k._)
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
