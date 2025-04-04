"use client";

import { PageSelector } from "@/components/PageSelector";
import { DiscordBot } from "@/lib/types";
import { useState } from "react";
import { FiCheck, FiEdit, FiXCircle } from "react-icons/fi";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { ClickableTableRow } from "@/components/table/ClickableTableRow";

const NUM_IN_PAGE = 20;

export function DiscordBotTable({
  discordBots,
}: {
  discordBots: DiscordBot[];
}) {
  const [page, setPage] = useState(1);

  // sort by id for consistent ordering
  discordBots.sort((a, b) => {
    if (a.id < b.id) {
      return -1;
    } else if (a.id > b.id) {
      return 1;
    } else {
      return 0;
    }
  });

  const discordBotsForPage = discordBots.slice(
    NUM_IN_PAGE * (page - 1),
    NUM_IN_PAGE * page
  );

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Channel Count</TableHead>
            <TableHead>Enabled</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {discordBotsForPage.map((discordBot) => {
            return (
              <ClickableTableRow
                url={`/admin/discord-bot/${discordBot.id}`}
                key={discordBot.id}
                className="hover:bg-muted cursor-pointer"
              >
                <TableCell>
                  <div className="flex items-center">
                    <FiEdit className="mr-4" />
                    {discordBot.name}
                  </div>
                </TableCell>
                <TableCell>{discordBot.configs_count}</TableCell>
                <TableCell>
                  {discordBot.enabled ? (
                    <FiCheck className="text-emerald-600" size="18" />
                  ) : (
                    <FiXCircle className="text-red-600" size="18" />
                  )}
                </TableCell>
              </ClickableTableRow>
            );
          })}
          {discordBots.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={4}
                className="text-center text-muted-foreground"
              >
                Please add a New Discord Bot to begin chatting with Onyx!
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {discordBots.length > NUM_IN_PAGE && (
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={Math.ceil(discordBots.length / NUM_IN_PAGE)}
              currentPage={page}
              onPageChange={(newPage) => {
                setPage(newPage);
                window.scrollTo({
                  top: 0,
                  left: 0,
                  behavior: "smooth",
                });
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
