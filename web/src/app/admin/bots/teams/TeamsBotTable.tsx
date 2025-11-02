import { TeamsBot } from "@/lib/types";
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
import { updateTeamsBotField } from "./lib";
import { useState } from "react";
import { useRouter } from "next/navigation";

const NUM_IN_PAGE = 10;

export const TeamsBotTable = ({ teamsBots }: { teamsBots: TeamsBot[] }) => {
  const router = useRouter();
  const [currentPage, setCurrentPage] = useState(1);

  const teamsBotsForPage = teamsBots.slice(
    (currentPage - 1) * NUM_IN_PAGE,
    currentPage * NUM_IN_PAGE
  );

  return (
    <div className="space-y-4">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Channel Configs</TableHead>
            <TableHead>Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {teamsBotsForPage.map((teamsBot) => {
            return (
              <TableRow
                key={teamsBot.id}
                className="cursor-pointer hover:bg-muted/50"
                onClick={() => {
                  router.push(`/admin/bots/teams/${teamsBot.id}`);
                }}
              >
                <TableCell className="font-medium">{teamsBot.name}</TableCell>
                <TableCell>
                  <Switch
                    checked={teamsBot.enabled}
                    onCheckedChange={async (checked) => {
                      await updateTeamsBotField(teamsBot, "enabled", checked);
                    }}
                  />
                </TableCell>
                <TableCell>{teamsBot.configs_count}</TableCell>
                <TableCell>
                  <Button
                    variant="ghost"
                    onClick={(e) => {
                      e.stopPropagation();
                      router.push(`/admin/bots/teams/${teamsBot.id}/channels`);
                    }}
                  >
                    Configure
                  </Button>
                </TableCell>
              </TableRow>
            );
          })}
          {teamsBots.length === 0 && (
            <TableRow>
              <TableCell colSpan={4} className="text-center">
                No Teams bots found
              </TableCell>
            </TableRow>
          )}
        </TableBody>
      </Table>
      {teamsBots.length > NUM_IN_PAGE && (
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
            disabled={currentPage * NUM_IN_PAGE >= teamsBots.length}
          >
            Next
          </Button>
        </div>
      )}
    </div>
  );
}; 