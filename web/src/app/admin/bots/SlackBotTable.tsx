"use client";

import { PageSelector } from "@/components/PageSelector";
import { SlackBot } from "@/lib/types";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FiCheck, FiEdit, FiXCircle } from "react-icons/fi";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

const NUM_IN_PAGE = 20;

function ClickableTableRow({
  url,
  children,
  ...props
}: {
  url: string;
  children: React.ReactNode;
  [key: string]: any;
}) {
  const router = useRouter();

  useEffect(() => {
    router.prefetch(url);
  }, [router]);

  const navigate = () => {
    router.push(url);
  };

  return (
    <TableRow {...props} onClick={navigate}>
      {children}
    </TableRow>
  );
}

export function SlackBotTable({ slackBots }: { slackBots: SlackBot[] }) {
  const [page, setPage] = useState(1);

  // sort by id for consistent ordering
  slackBots.sort((a, b) => {
    if (a.id < b.id) {
      return -1;
    } else if (a.id > b.id) {
      return 1;
    } else {
      return 0;
    }
  });

  const slackBotsForPage = slackBots.slice(
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
          {slackBotsForPage.map((slackBot) => {
            return (
              <ClickableTableRow
                url={`/admin/bots/${slackBot.id}`}
                key={slackBot.id}
                className="hover:bg-muted cursor-pointer"
              >
                <TableCell>
                  <div className="flex items-center">
                    <FiEdit className="mr-4" />
                    {slackBot.name}
                  </div>
                </TableCell>
                <TableCell>{slackBot.configs_count}</TableCell>
                <TableCell>
                  {slackBot.enabled ? (
                    <FiCheck className="text-emerald-600" size="18" />
                  ) : (
                    <FiXCircle className="text-red-600" size="18" />
                  )}
                </TableCell>
              </ClickableTableRow>
            );
          })}
          {slackBots.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={4}
                className="text-center text-muted-foreground"
              >
                Please add a New Slack Bot to begin chatting with Danswer!
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {slackBots.length > NUM_IN_PAGE && (
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={Math.ceil(slackBots.length / NUM_IN_PAGE)}
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
