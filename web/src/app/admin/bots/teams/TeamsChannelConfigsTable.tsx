import { TeamsChannelConfig } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { updateTeamsChannelConfig } from "./lib";
import { useState } from "react";
import { useRouter } from "next/navigation";

const NUM_IN_PAGE = 10;

export const TeamsChannelConfigsTable = ({
  channelConfigs,
  botId,
}: {
  channelConfigs: TeamsChannelConfig[];
  botId: string;
}) => {
  const router = useRouter();
  const [currentPage, setCurrentPage] = useState(1);

  const configsForPage = channelConfigs.slice(
    (currentPage - 1) * NUM_IN_PAGE,
    currentPage * NUM_IN_PAGE
  );

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Channel Name</TableHead>
            <TableHead>Channel ID</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {configsForPage.map((config) => {
            return (
              <TableRow
                key={config.id}
                className="cursor-pointer hover:bg-muted/50"
                onClick={() => {
                  router.push(`/admin/bots/teams/${botId}/channels/${config.id}`);
                }}
              >
                <TableCell className="font-medium">{config.channel_name}</TableCell>
                <TableCell>{config.channel_id}</TableCell>
                <TableCell>
                  <Switch
                    checked={config.enabled}
                    onCheckedChange={async (checked) => {
                      await updateTeamsChannelConfig(config.id, {
                        enabled: checked,
                      });
                    }}
                  />
                </TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    onClick={(e) => {
                      e.stopPropagation();
                      router.push(
                        `/admin/bots/teams/${botId}/channels/${config.id}`
                      );
                    }}
                  >
                    Configure
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
          {channelConfigs.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} className="text-center">
                No channel configurations found
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {channelConfigs.length > NUM_IN_PAGE && (
        <div className="flex justify-center">
          <Button
            variant="outline"
            onClick={() => setCurrentPage(currentPage - 1)}
            disabled={currentPage === 1}
          >
            Previous
          </Button>
          <Button
            variant="outline"
            onClick={() => setCurrentPage(currentPage + 1)}
            disabled={currentPage * NUM_IN_PAGE >= channelConfigs.length}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}; 