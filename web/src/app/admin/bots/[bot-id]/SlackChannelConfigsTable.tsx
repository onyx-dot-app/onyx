"use client";

import { PageSelector } from "@/components/PageSelector";
import { toast } from "@/hooks/useToast";
import { SvgEdit } from "@opal/icons";
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
import type { Route } from "next";
import { useState } from "react";
import { deleteSlackChannelConfig, isPersonaASlackBotPersona } from "./lib";
import { Card } from "@/components/ui/card";
import { Button } from "@opal/components";
import { SvgPlusCircle, SvgSettings, SvgTrash } from "@opal/icons";
const numToDisplay = 50;

export interface SlackChannelConfigsTableProps {
  slackBotId: number;
  slackChannelConfigs: SlackChannelConfig[];
  refresh: () => void;
}

export default function SlackChannelConfigsTable({
  slackBotId,
  slackChannelConfigs,
  refresh,
}: SlackChannelConfigsTableProps) {
  const [page, setPage] = useState(1);

  const defaultConfig = slackChannelConfigs.find((config) => config.is_default);
  const channelConfigs = slackChannelConfigs.filter(
    (config) => !config.is_default
  );

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center mb-6">
        <Button
          prominence="secondary"
          onClick={() => {
            window.location.href = `/admin/bots/${slackBotId}/channels/${defaultConfig?.id}`;
          }}
          icon={SvgSettings}
        >
          Edit Default Configuration
        </Button>
        <Button
          icon={SvgPlusCircle}
          prominence="secondary"
          href={`/admin/bots/${slackBotId}/channels/new`}
        >
          New Channel Configuration
        </Button>
      </div>

      <div>
        <h2 className="text-2xl font- mb-4">Channel-Specific Configurations</h2>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Channel</TableHead>
                <TableHead>Assistant</TableHead>
                <TableHead>Document Sets</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {channelConfigs
                .slice(numToDisplay * (page - 1), numToDisplay * page)
                .map((slackChannelConfig) => {
                  return (
                    <TableRow
                      key={slackChannelConfig.id}
                      className="cursor-pointer transition-colors"
                      onClick={() => {
                        window.location.href = `/admin/bots/${slackBotId}/channels/${slackChannelConfig.id}`;
                      }}
                    >
                      <TableCell>
                        <div className="flex gap-x-2">
                          <div className="my-auto">
                            <SvgEdit className="text-muted-foreground" />
                          </div>
                          <div className="my-auto">
                            {"#" +
                              slackChannelConfig.channel_config.channel_name}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        {slackChannelConfig.persona &&
                        !isPersonaASlackBotPersona(
                          slackChannelConfig.persona
                        ) ? (
                          <Link
                            href={
                              `/app/agents/edit/${slackChannelConfig.persona.id}` as Route
                            }
                            className="text-primary hover:underline"
                          >
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
                        <Button
                          onClick={async (e) => {
                            e.stopPropagation();
                            const response = await deleteSlackChannelConfig(
                              slackChannelConfig.id
                            );
                            if (response.ok) {
                              toast.success(
                                `Slack bot config "${slackChannelConfig.id}" deleted`
                              );
                            } else {
                              const errorMsg = await response.text();
                              toast.error(
                                `Failed to delete Slack bot config - ${errorMsg}`
                              );
                            }
                            refresh();
                          }}
                          icon={SvgTrash}
                          prominence="tertiary"
                          size="sm"
                        />
                      </TableCell>
                    </TableRow>
                  );
                })}

              {channelConfigs.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={4}
                    className="text-center text-muted-foreground"
                  >
                    No channel-specific configurations. Add a new configuration
                    to customize behavior for specific channels.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>

        {channelConfigs.length > numToDisplay && (
          <div className="mt-4 flex justify-center">
            <PageSelector
              totalPages={Math.ceil(channelConfigs.length / numToDisplay)}
              currentPage={page}
              onPageChange={(newPage) => setPage(newPage)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
