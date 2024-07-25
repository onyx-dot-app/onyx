import { PageSelector } from "@/components/PageSelector";
import { IndexAttemptStatus } from "@/components/Status";
import { ConnectorIndexingStatus } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
  Text,
} from "@tremor/react";
import Link from "next/link";
import { useState } from "react";
import { FiMaximize2 } from "react-icons/fi";

export function ReindexingProgressTable({
  reindexingProgress,
}: {
  reindexingProgress: ConnectorIndexingStatus<any, any>[];
}) {
  const numToDisplay = 10;
  const [page, setPage] = useState(1);

  return (
    <div>
      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Connector Name</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>Docs Re-Indexed</TableHeaderCell>
            <TableHeaderCell>Error Message</TableHeaderCell>
          </TableRow>
        </TableHead>
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
                    {reindexingProgress.latest_index_attempt?.status && (
                      <IndexAttemptStatus
                        status={reindexingProgress.latest_index_attempt.status}
                      />
                    )}
                  </TableCell>
                  <TableCell>
                    {reindexingProgress?.latest_index_attempt
                      ?.total_docs_indexed || "-"}
                  </TableCell>
                  <TableCell>
                    <div>
                      <Text className="flex flex-wrap whitespace-normal">
                        {reindexingProgress.error_msg || "-"}
                      </Text>
                    </div>
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
