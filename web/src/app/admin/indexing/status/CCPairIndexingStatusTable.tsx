import React, { useState, useMemo, useEffect } from "react";
import {
  Table,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Badge,
} from "@tremor/react";
import { IndexAttemptStatus } from "@/components/Status";
import { timeAgo } from "@/lib/time";
import {
  ConnectorIndexingStatus,
  ConnectorSummary,
  GroupedConnectorSummaries,
  ValidSources,
} from "@/lib/types";
import { useRouter } from "next/navigation";
import {
  FiCheck,
  FiChevronDown,
  FiChevronRight,
  FiSettings,
  FiXCircle,
} from "react-icons/fi";
import { Tooltip } from "@/components/tooltip/Tooltip";
import { SourceIcon } from "@/components/SourceIcon";
import { getSourceDisplayName } from "@/lib/sources";
import { CustomTooltip } from "@/components/tooltip/CustomTooltip";
import { Warning } from "@phosphor-icons/react";

const columnWidths = {
  first: "20%",
  second: "15%",
  third: "15%",
  fourth: "15%",
  fifth: "15%",
  sixth: "15%",
  seventh: "5%",
};

function SummaryRow({
  source,
  summary,
  isOpen,
  onToggle,
}: {
  source: ValidSources;
  summary: ConnectorSummary;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const activePercentage = (summary.active / summary.count) * 100;

  return (
    <TableRow
      onClick={onToggle}
      className="border-border bg-white rounded-sm !border sbg-white cursor-pointer"
    >
      <TableCell className={`py-4 w-[${columnWidths.first}]`}>
        <div className="text-xl flex items-center truncate ellipsis gap-x-2 font-semibold">
          <div className="cursor-pointer">
            {isOpen ? (
              <FiChevronDown size={20} />
            ) : (
              <FiChevronRight size={20} />
            )}
          </div>
          <SourceIcon iconSize={20} sourceType={source} />
          {getSourceDisplayName(source)}
        </div>
      </TableCell>

      <TableCell className={`py-4 w-[${columnWidths.first}]`}>
        <div className="text-sm text-gray-500">Total Connectors</div>
        <div className="text-xl font-semibold">{summary.count}</div>
      </TableCell>

      <TableCell className={` py-4 w-[${columnWidths.second}]`}>
        <div className="text-sm text-gray-500">Active Connectors</div>
        <Tooltip
          content={`${summary.active} out of ${summary.count} connectors are active`}
        >
          <div className="flex items-center mt-1">
            <div className="w-full bg-gray-200 rounded-full h-2 mr-2">
              <div
                className="bg-green-500 h-2 rounded-full"
                style={{ width: `${activePercentage}%` }}
              ></div>
            </div>
            <span className="text-sm font-medium whitespace-nowrap">
              {summary.active} ({activePercentage.toFixed(0)}%)
            </span>
          </div>
        </Tooltip>
      </TableCell>

      <TableCell className={`py-4 w-[${columnWidths.fourth}]`}>
        <div className="text-sm text-gray-500">Public Connectors</div>
        <p className="flex text-xl mx-auto font-semibold items-center text-lg mt-1">
          {summary.public}/{summary.count}
        </p>
      </TableCell>

      <TableCell className={`py-4 w-[${columnWidths.fifth}]`}>
        <div className="text-sm text-gray-500">Total Docs Indexed</div>
        <div className="text-xl font-semibold">
          {summary.totalDocsIndexed.toLocaleString()}
        </div>
      </TableCell>

      <TableCell className={`w-[${columnWidths.sixth}]`}>
        <div className="text-sm text-gray-500">Errors</div>

        <div className="flex items-center text-lg gap-x-1 font-semibold">
          {summary.errors > 0 && <Warning className="text-error h-6 w-6" />}
          {summary.errors}
        </div>
      </TableCell>

      <TableCell className={`w-[${columnWidths.seventh}]`}></TableCell>
    </TableRow>
  );
}

function ConnectorRow({
  ccPairsIndexingStatus,
  invisible,
}: {
  ccPairsIndexingStatus: any;
  invisible?: boolean;
}) {
  const router = useRouter();

  const handleManageClick = (e: any) => {
    e.stopPropagation();
    router.push(`/admin/connector/${ccPairsIndexingStatus.cc_pair_id}`);
  };

  const getActivityBadge = () => {
    if (ccPairsIndexingStatus.connector.disabled) {
      if (ccPairsIndexingStatus.deletion_attempt) {
        return (
          <Badge
            color="red"
            className="w-fit px-2 py-1 rounded-full border border-red-500"
          >
            <div className="flex text-xs items-center gap-x-1">
              <div className="w-3 h-3 rounded-full bg-red-500"></div>
              Deleting
            </div>
          </Badge>
        );
      }
      return (
        <Badge
          color="yellow"
          className="w-fit px-2 py-1 rounded-full border border-yellow-500"
        >
          <div className="flex text-xs items-center gap-x-1">
            <div className="w-3 h-3 rounded-full bg-yellow-500"></div>
            Paused
          </div>
        </Badge>
      );
    }
    switch (ccPairsIndexingStatus.last_status) {
      case "in_progress":
        return (
          <Badge
            color="green"
            className="w-fit px-2 py-1 rounded-full border border-green-500"
          >
            <div className="flex text-xs items-center gap-x-1">
              <div className="w-3 h-3 rounded-full bg-green-500"></div>
              Indexing
            </div>
          </Badge>
        );
      case "not_started":
        return (
          <Badge
            color="purple"
            className="w-fit px-2 py-1 rounded-full border border-purple-500"
          >
            <div className="flex text-xs items-center gap-x-1">
              <div className="w-3 h-3 rounded-full bg-purple-500"></div>
              Scheduled
            </div>
          </Badge>
        );
      default:
        return (
          <Badge
            color="green"
            className="w-fit px-2 py-1 rounded-full border border-green-500"
          >
            <div className="flex text-xs items-center gap-x-1">
              <div className="w-3 h-3 rounded-full bg-green-500"></div>
              Active
            </div>
          </Badge>
        );
    }
  };

  return (
    <TableRow
      className={`hover:bg-hover-light ${invisible ? "invisible h-0 !-mb-10" : "border border-border !border-b"}  w-full cursor-pointer relative`}
      onClick={() =>
        router.push(`/admin/connector/${ccPairsIndexingStatus.cc_pair_id}`)
      }
    >
      <TableCell className={`!pr-0 w-[${columnWidths.first}]`}>
        <p className="w-[200px] inline-block ellipsis truncate">
          {ccPairsIndexingStatus.name}
        </p>
      </TableCell>
      <TableCell className={` w-[${columnWidths.fifth}]`}>
        {timeAgo(ccPairsIndexingStatus?.last_success) || "-"}
      </TableCell>
      <TableCell className={`w-[${columnWidths.third}]`}>
        {getActivityBadge()}
      </TableCell>
      <TableCell className={`w-[${columnWidths.fourth}]`}>
        {ccPairsIndexingStatus.public_doc ? (
          <FiCheck className="my-auto text-emerald-600" size="18" />
        ) : (
          <FiXCircle className="my-auto text-red-600" />
        )}
      </TableCell>
      <TableCell className={`w-[${columnWidths.sixth}]`}>
        {ccPairsIndexingStatus.docs_indexed}
      </TableCell>
      <TableCell className={`w-[${columnWidths.second}]`}>
        <IndexAttemptStatus
          status={ccPairsIndexingStatus.last_finished_status || null}
          errorMsg={ccPairsIndexingStatus?.latest_index_attempt?.error_msg}
          size="xs"
        />
      </TableCell>
      <TableCell className={`w-[${columnWidths.seventh}]`}>
        <CustomTooltip content="Manage Connector">
          <FiSettings className="cursor-pointer" onClick={handleManageClick} />
        </CustomTooltip>
      </TableCell>
    </TableRow>
  );
}

export function CCPairIndexingStatusTable({
  ccPairsIndexingStatuses,
}: {
  ccPairsIndexingStatuses: ConnectorIndexingStatus<any, any>[];
}) {
  const [allToggleTracker, setAllToggleTracker] = useState(true);
  const [openSources, setOpenSources] = useState<Record<ValidSources, boolean>>(
    {} as Record<ValidSources, boolean>
  );

  const { groupedStatuses, sortedSources, groupSummaries } = useMemo(() => {
    const grouped: Record<ValidSources, ConnectorIndexingStatus<any, any>[]> =
      {} as Record<ValidSources, ConnectorIndexingStatus<any, any>[]>;
    ccPairsIndexingStatuses.forEach((status) => {
      const source = status.connector.source;
      if (!grouped[source]) {
        grouped[source] = [];
      }
      grouped[source].push(status);
    });

    const sorted = Object.keys(grouped).sort() as ValidSources[];

    const summaries: GroupedConnectorSummaries =
      {} as GroupedConnectorSummaries;
    sorted.forEach((source) => {
      const statuses = grouped[source];
      summaries[source] = {
        count: statuses.length,
        active: statuses.filter((status) => !status.connector.disabled).length,
        public: statuses.filter((status) => status.public_doc).length,
        totalDocsIndexed: statuses.reduce(
          (sum, status) => sum + status.docs_indexed,
          0
        ),
        errors: statuses.filter((status) => status.last_status === "failed")
          .length,
      };
    });

    return {
      groupedStatuses: grouped,
      sortedSources: sorted,
      groupSummaries: summaries,
    };
  }, [ccPairsIndexingStatuses]);

  const toggleSource = (source: ValidSources) => {
    setOpenSources((prev) => ({
      ...prev,
      [source]: !prev[source],
    }));
  };

  const toggleSources = (toggle: boolean) => {
    const updatedSources = Object.fromEntries(
      sortedSources.map((item) => [item, toggle])
    );
    setOpenSources(updatedSources as Record<ValidSources, boolean>);
    setAllToggleTracker(!toggle);
  };

  const router = useRouter();
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.metaKey || event.ctrlKey) {
        switch (event.key.toLowerCase()) {
          case "e":
            toggleSources(false);
            event.preventDefault();
            break;
        }
      }
    };
    toggleSources(true);
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [router, allToggleTracker]);

  return (
    <div className="-mt-20">
      <Table>
        <ConnectorRow
          invisible
          ccPairsIndexingStatus={{
            cc_pair_id: 1,
            name: "Sample File Connector",
            last_status: "success",
            connector: {
              source: "file",
              disabled: false,
            },
            public_doc: true,
            docs_indexed: 1000,
            last_success: "2023-07-01T12:00:00Z",
          }}
        />
        <div className="-mb-10" />
        <TableBody>
          {sortedSources.map((source, ind) => (
            <React.Fragment key={ind}>
              <div className="mt-4" />

              <SummaryRow
                source={source}
                summary={groupSummaries[source]}
                isOpen={openSources[source] || false}
                onToggle={() => toggleSource(source)}
              />

              {openSources[source] && (
                <>
                  <TableRow className="border border-border">
                    <TableHeaderCell className={`w-[${columnWidths.first}]`}>
                      Name
                    </TableHeaderCell>
                    <TableHeaderCell className={`w-[${columnWidths.fifth}]`}>
                      Last Indexed
                    </TableHeaderCell>
                    <TableHeaderCell className={`w-[${columnWidths.second}]`}>
                      Activity
                    </TableHeaderCell>
                    <TableHeaderCell className={`w-[${columnWidths.fourth}]`}>
                      Public
                    </TableHeaderCell>
                    <TableHeaderCell className={`w-[${columnWidths.sixth}]`}>
                      Total Docs
                    </TableHeaderCell>
                    <TableHeaderCell className={`w-[${columnWidths.third}]`}>
                      Last Status
                    </TableHeaderCell>
                    <TableHeaderCell
                      className={`w-[${columnWidths.seventh}]`}
                    ></TableHeaderCell>
                  </TableRow>
                  {groupedStatuses[source].map((ccPairsIndexingStatus) => (
                    <ConnectorRow
                      key={ccPairsIndexingStatus.cc_pair_id}
                      ccPairsIndexingStatus={ccPairsIndexingStatus}
                    />
                  ))}
                </>
              )}
            </React.Fragment>
          ))}
        </TableBody>

        {/* Padding between table and bottom of page */}
        <div className="invisible w-full pb-40" />
      </Table>
    </div>
  );
}
