"use client";

import { PageSelector } from "@/components/PageSelector";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { EditIcon, TrashIcon } from "@/components/icons/icons";
import { SlackShortcutConfig } from "@/lib/types";
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
import { deleteSlackShortcutConfig, isPersonaASlackBotPersona } from "./shortcuts-lib";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { FiPlusSquare, FiSettings } from "react-icons/fi";

const numToDisplay = 50;

export function SlackShortcutConfigsTable({
  slackBotId,
  slackShortcutConfigs,
  refresh,
  setPopup,
}: {
  slackBotId: number;
  slackShortcutConfigs: SlackShortcutConfig[];
  refresh: () => void;
  setPopup: (popupSpec: PopupSpec | null) => void;
}) {
  const [page, setPage] = useState(1);

  const shortcutConfigs = slackShortcutConfigs.filter(
    (config) => !config.is_default
  );

  return (
    <div className="space-y-8">
      <div>
        <h2 className="text-2xl font- mb-4">Shortcut Configurations</h2>
        <Card>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Shortcut</TableHead>
                <TableHead>Default Message</TableHead>
                <TableHead>Assistant</TableHead>
                <TableHead>Document Sets</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {shortcutConfigs
                .slice(numToDisplay * (page - 1), numToDisplay * page)
                .map((slackShortcutConfig) => {
                  return (
                    <TableRow
                      key={slackShortcutConfig.id}
                      className="cursor-pointer transition-colors"
                      onClick={() => {
                        window.location.href = `/admin/bots/${slackBotId}/shortcuts/${slackShortcutConfig.id}`;
                      }}
                    >
                      <TableCell>
                        <div className="flex gap-x-2">
                          <div className="my-auto">
                            <EditIcon className="text-muted-foreground" />
                          </div>
                          <div className="my-auto">
                            {slackShortcutConfig.shortcut_config.shortcut_name}
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="truncate max-w-xs">
                          {slackShortcutConfig.shortcut_config.default_message || "-"}
                        </div>
                      </TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        {slackShortcutConfig.persona &&
                        !isPersonaASlackBotPersona(
                          slackShortcutConfig.persona
                        ) ? (
                          <Link
                            href={`/assistants/${slackShortcutConfig.persona.id}`}
                            className="text-primary hover:underline"
                          >
                            {slackShortcutConfig.persona.name}
                          </Link>
                        ) : (
                          "-"
                        )}
                      </TableCell>
                      <TableCell>
                        <div>
                          {slackShortcutConfig.persona &&
                          slackShortcutConfig.persona.document_sets.length > 0
                            ? slackShortcutConfig.persona.document_sets
                                .map((documentSet) => documentSet.name)
                                .join(", ")
                            : "-"}
                        </div>
                      </TableCell>
                      <TableCell onClick={(e) => e.stopPropagation()}>
                        <Button
                          variant="ghost"
                          size="sm"
                          className="hover:text-destructive"
                          onClick={async (e) => {
                            e.stopPropagation();
                            const response = await deleteSlackShortcutConfig(
                              slackShortcutConfig.id
                            );
                            if (response.ok) {
                              setPopup({
                                message: `Slack shortcut config "${slackShortcutConfig.shortcut_config.shortcut_name}" deleted`,
                                type: "success",
                              });
                            } else {
                              const errorMsg = await response.text();
                              setPopup({
                                message: `Failed to delete Slack shortcut config - ${errorMsg}`,
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

              {shortcutConfigs.length === 0 && (
                <TableRow>
                  <TableCell
                    colSpan={5}
                    className="text-center text-muted-foreground"
                  >
                    No shortcut configurations. Add a new shortcut configuration
                    to create custom Slack shortcuts for your team.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>

        {shortcutConfigs.length > numToDisplay && (
          <div className="mt-4 flex justify-center">
            <PageSelector
              totalPages={Math.ceil(shortcutConfigs.length / numToDisplay)}
              currentPage={page}
              onPageChange={(newPage) => setPage(newPage)}
            />
          </div>
        )}
      </div>
    </div>
  );
}