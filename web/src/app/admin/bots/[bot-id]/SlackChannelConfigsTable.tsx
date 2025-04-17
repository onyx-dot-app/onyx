"use client";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";

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
import { deleteSlackChannelConfig, isPersonaASlackBotPersona } from "./lib";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FiPlusSquare, FiSettings } from "react-icons/fi";

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

  const defaultConfig = slackChannelConfigs.find((config) => config.is_default);
  const channelConfigs = slackChannelConfigs.filter(
    (config) => !config.is_default
  );

  return (
    <div className="space-y-8">
      <div className="flex justify-between items-center mb-6">
        <Button
          variant="outline"
          onClick={() => {
            window.location.href = `/admin/bots/${slackBotId}/channels/${defaultConfig?.id}`;
          }}
        >
          <FiSettings />
          {i18n.t(k.EDIT_DEFAULT_CONFIGURATION)}
        </Button>
        <Link href={`/admin/bots/${slackBotId}/channels/new`}>
          <Button variant="outline">
            <FiPlusSquare />
            {i18n.t(k.NEW_CHANNEL_CONFIGURATION)}
          </Button>
        </Link>
      </div>

      <div>
        <h2 className="text-2xl font- mb-4">
          {i18n.t(k.CHANNEL_SPECIFIC_CONFIGURATION)}
        </h2>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{i18n.t(k.CHANNEL)}</TableHead>
                <TableHead>{i18n.t(k.ASSISTANT)}</TableHead>
                <TableHead>{i18n.t(k.DOCUMENT_SETS)}</TableHead>
                <TableHead>{i18n.t(k.ACTIONS)}</TableHead>
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
                            <EditIcon className="text-muted-foreground" />
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
                            href={`/assistants/${slackChannelConfig.persona.id}`}
                            className="text-primary hover:underline"
                          >
                            {slackChannelConfig.persona.name}
                          </Link>
                        ) : (
                          i18n.t(k._)
                        )}
                      </TableCell>
                      <TableCell>
                        <div>
                          {slackChannelConfig.persona &&
                          slackChannelConfig.persona.document_sets.length > 0
                            ? slackChannelConfig.persona.document_sets
                                .map((documentSet) => documentSet.name)
                                .join(i18n.t(k._3))
                            : i18n.t(k._)}
                        </div>
                      </TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="hover:text-destructive"
                          onClick={async (e) => {
                            e.stopPropagation();
                            const response = await deleteSlackChannelConfig(
                              slackChannelConfig.id
                            );
                            if (response.ok) {
                              setPopup({
                                message: `${i18n.t(k.SLACK_BOT_CONFIG)}${
                                  slackChannelConfig.id
                                }${i18n.t(k.DELETED)}`,
                                type: "success",
                              });
                            } else {
                              const errorMsg = await response.text();
                              setPopup({
                                message: `${i18n.t(
                                  k.FAILED_TO_DELETE_SLACK_BOT_CON
                                )} ${errorMsg}`,
                                type: "error",
                              });
                            }
                            refresh();
                          }}
                        >
                          <TrashIcon />
                        </Button>
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
                    {i18n.t(k.NO_CHANNEL_SPECIFIC_CONFIGURAT)}
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
