import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { ChevronDown, ChevronUp, CheckCircle, Users } from "lucide-react";
import { useState } from "react";
import { PageSelector } from "@/components/PageSelector";
import { UserGroup } from "@/lib/types";
import { SyncRecord } from "@/app/admin/connector/[ccPairId]/types";

// Helper function to format date
const formatDateTime = (date: Date): string => {
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
};

interface GroupSyncStatusTableProps {
  userGroup: UserGroup;
  syncRecords: SyncRecord[];
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
  lastSyncTime?: string | null;
}

export function GroupSyncStatusTable({
  userGroup,
  syncRecords,
  currentPage,
  totalPages,
  onPageChange,
  lastSyncTime,
}: GroupSyncStatusTableProps) {
  const hasPagination = totalPages > 1;
  const [isExpanded, setIsExpanded] = useState(false);

  // Filter to only show user group syncs
  const filteredRecords =
    syncRecords?.filter((record) => record.sync_type === "user_group") || [];

  // Check if we have any records to show
  if (filteredRecords.length === 0 && currentPage === 0) {
    return (
      <div className="text-sm text-gray-500 italic my-2">
        No group sync records found
      </div>
    );
  }

  // Estimate the total number of users synced
  const totalUsersSynced = userGroup.users?.length || 0;

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setIsExpanded(!isExpanded)}
            className="mr-2 text-muted-foreground"
          >
            {isExpanded ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            {isExpanded ? "Hide details" : "Show sync history"}
          </Button>
          <div className="text-sm">
            <span className="flex items-center text-green-600 dark:text-green-400">
              <CheckCircle className="h-4 w-4 mr-1 inline" />
              Groups synced
            </span>
          </div>
        </div>
      </div>

      {lastSyncTime && (
        <div className="text-sm text-muted-foreground mb-2">
          Last synced: {new Date(lastSyncTime).toLocaleString()}
        </div>
      )}

      {isExpanded && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Docs Processed</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredRecords.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-center py-4">
                    No group sync records found
                  </TableCell>
                </TableRow>
              ) : (
                filteredRecords.map((record) => (
                  <TableRow key={record.id}>
                    <TableCell>
                      {formatDateTime(new Date(record.created_at))}
                    </TableCell>
                    <TableCell>
                      <span className="flex items-center text-green-600 dark:text-green-400">
                        <CheckCircle className="h-4 w-4 mr-1" /> Success
                      </span>
                    </TableCell>
                    <TableCell>{record.num_docs_synced}</TableCell>
                  </TableRow>
                ))
              )}
            </TableBody>
          </Table>

          {hasPagination && (
            <div className="flex justify-end mt-4">
              <PageSelector
                currentPage={currentPage}
                totalPages={totalPages}
                onPageChange={onPageChange}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
