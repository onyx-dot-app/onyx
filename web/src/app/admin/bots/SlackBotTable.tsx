"use client";

import { PageSelector } from "@/components/PageSelector";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SlackBot } from "@/lib/types";
import { EditIcon } from "@/components/icons/icons";

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
  }, [router, url]);

  const navigate = () => {
    router.push(url);
  };

  return (
    <TableRow {...props} onClick={navigate}>
      {children}
    </TableRow>
  );
}

export const SlackBotTable = ({ slackBots }: { slackBots: SlackBot[] }) => {
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
            <TableHead>Status</TableHead>
            <TableHead>Default Config</TableHead>
            <TableHead>Channel Count</TableHead>
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
                    <EditIcon className="mr-4" />
                    {slackBot.name}
                  </div>
                </TableCell>
                <TableCell>
                  {slackBot.enabled ? (
                    <Badge variant="success">Enabled</Badge>
                  ) : (
                    <Badge variant="destructive">Disabled</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">Default Set</Badge>
                </TableCell>
                <TableCell>{slackBot.configs_count}</TableCell>
                <TableCell>
                  {/* Add any action buttons here if needed */}
                </TableCell>
              </ClickableTableRow>
            );
          })}
          {slackBots.length === 0 && (
            <TableRow>
              <TableCell
                colSpan={5}
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
};
