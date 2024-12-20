"use client";

import { PageSelector } from "@/components/PageSelector";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { EditIcon, TrashIcon } from "@/components/icons/icons";
import { SlackChannelConfig } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import Link from "next/link";
import { useState } from "react";
import { FiArrowUpRight } from "react-icons/fi";
import { deleteSlackChannelConfig, isPersonaASlackBotPersona } from "./lib";

const numToDisplay = 50;

export function SlackChannelConfigsTable({
  slackBotId,
  slackChannelConfigs,
  refresh,
  setPopup,
}: {
  slackBotId: number;
  slackChannelConfigs: SlackChannelConfig[];
  refresh: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
}) {
  const [page, setPage] = useState(1);

  // sort by name for consistent ordering
  slackChannelConfigs.sort((a, b) => {
    if (a.id < b.id) {
      return -1;
    } else if (a.id > b.id) {
      return 1;
    } else {
      return 0;
    }
  });

  return (
    <div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Channel</TableHead>
              <TableHead>Persona</TableHead>
              <TableHead>Document Sets</TableHead>
              <TableHead>Delete</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {slackChannelConfigs
              .slice(numToDisplay * (page - 1), numToDisplay * page)
              .map((slackChannelConfig) => {
                return (
                  <TableRow
                    key={slackChannelConfig.id}
                    className="cursor-pointer hover:bg-gray-100 transition-colors"
                    onClick={() => {
                      window.location.href = `/admin/bots/${slackBotId}/channels/${slackChannelConfig.id}`;
                    }}
                  >
                    <TableCell>
                      <div className="flex gap-x-2">
                        <div className="my-auto">
                          <EditIcon />
                        </div>
                        <div className="my-auto">
                          {"#" + slackChannelConfig.channel_config.channel_name}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      {slackChannelConfig.persona &&
                      !isPersonaASlackBotPersona(slackChannelConfig.persona) ? (
                        <Link
                          href={`/admin/assistants/${slackChannelConfig.persona.id}`}
                          className="text-blue-500 flex hover:underline"
                        >
                          <FiArrowUpRight className="my-auto mr-1" />
                          {slackChannelConfig.persona.name}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </TableCell>
                    <TableCell>
                      <div>
                        {slackChannelConfig.persona &&
                        slackChannelConfig.persona.document_sets.length > 0
                          ? slackChannelConfig.persona.document_sets
                              .map((documentSet) => documentSet.name)
                              .join(", ")
                          : "-"}
                      </div>
                    </TableCell>
                    <TableCell onClick={(e) => e.stopPropagation()}>
                      <div
                        className="cursor-pointer hover:text-destructive"
                        onClick={async (e) => {
                          e.stopPropagation();
                          const response = await deleteSlackChannelConfig(
                            slackChannelConfig.id
                          );
                          if (response.ok) {
                            setPopup({
                              message: `Slack bot config "${slackChannelConfig.id}" deleted`,
                              type: "success",
                            });
                          } else {
                            const errorMsg = await response.text();
                            setPopup({
                              message: `Failed to delete Slack bot config - ${errorMsg}`,
                              type: "error",
                            });
                          }
                          refresh();
                        }}
                      >
                        <TrashIcon />
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}

            {/* Empty row with message when table has no data */}
            {slackChannelConfigs.length === 0 && (
              <TableRow>
                <TableCell
                  colSpan={4}
                  className="text-center text-muted-foreground"
                >
                  Please add a New Slack Bot Configuration to begin chatting
                  with Danswer!
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      <div className="mt-3 flex">
        <div className="mx-auto">
          <PageSelector
            totalPages={Math.ceil(slackChannelConfigs.length / numToDisplay)}
            currentPage={page}
            onPageChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
}
