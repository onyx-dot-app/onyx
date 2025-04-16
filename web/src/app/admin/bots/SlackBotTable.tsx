"use client";
import i18n from "i18next";
import k from "./../../../i18n/keys";

import { PageSelector } from "@/components/PageSelector";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { FiEdit } from "react-icons/fi";
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
            <TableHead>{i18n.t(k.NAME)}</TableHead>
            <TableHead>{i18n.t(k.STATUS)}</TableHead>
            <TableHead>{i18n.t(k.DEFAULT_CONFIG)}</TableHead>
            <TableHead>{i18n.t(k.CHANNEL_COUNT)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {slackBotsForPage.map((slackBot) => {
            return (
              <ClickableTableRow
                url={`${i18n.t(k.ADMIN_BOTS)}${slackBot.id}`}
                key={slackBot.id}
                className="hover:bg-muted cursor-pointer"
              >
                <TableCell>
                  <div className="flex items-center">
                    <FiEdit className="mr-4" />
                    {slackBot.name}
                  </div>
                </TableCell>
                <TableCell>
                  {slackBot.enabled ? (
                    <Badge variant="success">{i18n.t(k.ENABLED)}</Badge>
                  ) : (
                    <Badge variant="destructive">{i18n.t(k.DISABLED)}</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <Badge variant="secondary">{i18n.t(k.DEFAULT_SET)}</Badge>
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
                {i18n.t(k.PLEASE_ADD_A_NEW_SLACK_BOT_TO)}
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
                  behavior: i18n.t(k.SMOOTH),
                });
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
};
