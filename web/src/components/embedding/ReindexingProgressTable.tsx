import { PageSelector } from "@/components/PageSelector";
import { IndexAttemptStatus } from "@/components/Status";
import {
  ConnectorIndexingStatus,
  ConnectorIndexingStatusLite,
} from "@/lib/types";
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
import { FiMaximize2 } from "react-icons/fi";

export function ReindexingProgressTable({
  reindexingProgress,
}: {
  reindexingProgress: ConnectorIndexingStatusLite[];
}) {
  const numToDisplay = 10;
  const [page, setPage] = useState(1);

  return (
    <div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="w-1/7 sm:w-1/5">Connector Name</TableHead>
            <TableHead className="w-3/7 sm:w-1/5">Status</TableHead>
            <TableHead className="w-3/7 sm:w-1/5">Docs Re-Indexed</TableHead>
            <TableHead className="w-3/7 sm:w-1/5"></TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {reindexingProgress
            .slice(numToDisplay * (page - 1), numToDisplay * page)
            .map((reindexingProgress) => {
              return (
                <TableRow key={reindexingProgress.name}>
                  <TableCell>
                    <Link
                      href={`/admin/connector/${reindexingProgress.cc_pair_id}`}
                      className="text-link cursor-pointer flex"
                    >
                      <FiMaximize2 className="my-auto mr-1" />
                      {reindexingProgress.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    {reindexingProgress.last_status && (
                      <IndexAttemptStatus
                        status={reindexingProgress.last_status}
                      />
                    )}
                  </TableCell>
                  <TableCell>
                    {reindexingProgress?.latest_index_attempt_docs_indexed ||
                      "-"}
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>

      <div className="mt-3 flex">
        <div className="mx-auto">
          <PageSelector
            totalPages={Math.ceil(reindexingProgress.length / numToDisplay)}
            currentPage={page}
            onPageChange={(newPage) => setPage(newPage)}
          />
        </div>
      </div>
    </div>
  );
}
