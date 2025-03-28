import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { CCPairFullInfo, SyncRecord } from "./types";
import { Button } from "@/components/ui/button";
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  CheckCircle,
} from "lucide-react";
import { useState } from "react";
import { AttemptStatus } from "@/components/Status";
import { PageSelector } from "@/components/PageSelector";

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

interface SyncStatus {
  status: string;
}

interface SyncStatusTableProps {
  ccPair: CCPairFullInfo;
  syncRecords: SyncRecord[];
  currentPage: number;
  totalPages: number;
  onPageChange: (page: number) => void;
}

export function SyncStatusTable({
  ccPair,
  syncRecords,
  currentPage,
  totalPages,
  onPageChange,
}: SyncStatusTableProps) {
  const hasPagination = totalPages > 1;
  const [isExpanded, setIsExpanded] = useState(false);

  // Filter to only show external permissions
  const filteredRecords =
    syncRecords?.filter(
      (record) => record.sync_type === "external_permissions"
    ) || [];

  // Check if we have any records to show
  if (filteredRecords.length === 0 && currentPage === 0) {
    return (
      <div className="text-sm text-gray-500 italic my-2">
        No permissions sync records found
      </div>
    );
  }

  // The total documents synced is the total number of documents in the cc_pair
  const totalDocsSynced = ccPair.num_docs_indexed || 0;

  return (
    <div className="mb-6">
      <div className="flex items-center mb-2">
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
            Permissions sync enabled • {totalDocsSynced} documents synced
          </span>
        </div>
      </div>

      {isExpanded && (
        <>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Status</TableHead>
                <TableHead></TableHead>
                <TableHead>Docs Processed</TableHead>
                <TableHead>Error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filteredRecords.length === 0 ? (
                <TableRow>
                  <TableCell colSpan={3} className="text-center py-4">
                    No permission sync records found
                  </TableCell>
                </TableRow>
              ) : (
                filteredRecords.map((record, index) => (
                  <TableRow key={record.id}>
                    <TableCell>
                      {formatDateTime(new Date(record.created_at))}
                    </TableCell>
                    <TableCell>
                      <AttemptStatus status={record.sync_status as any} />
                    </TableCell>
                    <TableCell></TableCell>

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
