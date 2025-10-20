import React from "react";
import {
  Table,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { CCPairStatus } from "@/components/Status";
import { timeAgo } from "@/lib/time";
import {
  ValidSources,
  ConnectorIndexingStatusLiteResponse,
  SourceSummary,
  ConnectorIndexingStatusLite,
  FederatedConnectorStatus,
} from "@/lib/types";
import { useRouter } from "next/navigation";
import {
  FiChevronDown,
  FiChevronRight,
  FiSettings,
  FiLock,
  FiUnlock,
  FiRefreshCw,
} from "react-icons/fi";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SourceIcon } from "@/components/SourceIcon";
import { getSourceDisplayName } from "@/lib/sources";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { ConnectorCredentialPairStatus } from "../../connector/[ccPairId]/types";
import { PageSelector } from "@/components/PageSelector";
import { ConnectorStaggeredSkeleton } from "./ConnectorRowSkeleton";
import Text from "@/refresh-components/texts/Text";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgSettings from "@/icons/settings";

function isFederatedConnectorStatus(
  status: ConnectorIndexingStatusLite | FederatedConnectorStatus
) {
  return status.name?.toLowerCase().includes("federated");
}

const NUMBER_OF_ROWS_PER_PAGE = 10;
const NUMBER_OF_COLUMNS = 6;
function SummaryRow({
  source,
  summary,
  isOpen,
  onToggle,
}: {
  source: ValidSources;
  summary: SourceSummary;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  return (
    <TableRow
      onClick={onToggle}
      className="border-border dark:hover:bg-neutral-800 dark:border-neutral-700 group hover:bg-background-settings-hover/20 bg-background-sidebar py-4 rounded-sm !border cursor-pointer"
    >
      <TableCell>
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

      <TableCell>
        <div className="text-sm text-neutral-500 dark:text-neutral-300">
          Total Connectors
        </div>
        <div className="text-xl font-semibold">{summary.total_connectors}</div>
      </TableCell>

      <TableCell>
        <div className="text-sm text-neutral-500 dark:text-neutral-300">
          Active Connectors
        </div>
        <p className="flex text-xl mx-auto font-semibold items-center text-lg mt-1">
          {summary.active_connectors}/{summary.total_connectors}
        </p>
      </TableCell>

      {isPaidEnterpriseFeaturesEnabled && (
        <TableCell>
          <div className="text-sm text-neutral-500 dark:text-neutral-300">
            Public Connectors
          </div>
          <p className="flex text-xl mx-auto font-semibold items-center text-lg mt-1">
            {summary.public_connectors}/{summary.total_connectors}
          </p>
        </TableCell>
      )}

      <TableCell>
        <div className="text-sm text-neutral-500 dark:text-neutral-300">
          Total Docs Indexed
        </div>
        <div className="text-xl font-semibold">
          {summary.total_docs_indexed.toLocaleString()}
        </div>
      </TableCell>

      <TableCell />
    </TableRow>
  );
}

function ConnectorRow({
  ccPairsIndexingStatus,
  invisible,
  isEditable,
}: {
  ccPairsIndexingStatus: ConnectorIndexingStatusLite;
  invisible?: boolean;
  isEditable: boolean;
}) {
  const router = useRouter();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const handleManageClick = (e: any) => {
    e.stopPropagation();
    router.push(`/admin/connector/${ccPairsIndexingStatus.cc_pair_id}`);
  };

  return (
    <TableRow
      className={`
  border border-border dark:border-neutral-700
          hover:bg-accent-background ${
            invisible
              ? "invisible !h-0 !-mb-10 !border-none"
              : "!border border-border dark:border-neutral-700"
          }  w-full cursor-pointer relative `}
      onClick={() => {
        router.push(`/admin/connector/${ccPairsIndexingStatus.cc_pair_id}`);
      }}
    >
      <TableCell className="">
        <p className="lg:w-[200px] xl:w-[400px] inline-block ellipsis truncate">
          {ccPairsIndexingStatus.name}
        </p>
      </TableCell>
      <TableCell>
        {timeAgo(ccPairsIndexingStatus?.last_success) || "-"}
      </TableCell>
      <TableCell>
        <CCPairStatus
          ccPairStatus={
            ccPairsIndexingStatus.last_finished_status !== null
              ? ccPairsIndexingStatus.cc_pair_status
              : ccPairsIndexingStatus.last_status == "not_started"
                ? ConnectorCredentialPairStatus.SCHEDULED
                : ConnectorCredentialPairStatus.INITIAL_INDEXING
          }
          inRepeatedErrorState={ccPairsIndexingStatus.in_repeated_error_state}
          lastIndexAttemptStatus={ccPairsIndexingStatus.last_status}
        />
      </TableCell>
      {isPaidEnterpriseFeaturesEnabled && (
        <TableCell>
          {ccPairsIndexingStatus.access_type === "public" ? (
            <Badge variant={isEditable ? "success" : "default"} icon={FiUnlock}>
              Organization Public
            </Badge>
          ) : ccPairsIndexingStatus.access_type === "sync" ? (
            <Badge
              variant={isEditable ? "auto-sync" : "default"}
              icon={FiRefreshCw}
            >
              Inherited from{" "}
              {getSourceDisplayName(ccPairsIndexingStatus.source)}
            </Badge>
          ) : (
            <Badge variant={isEditable ? "private" : "default"} icon={FiLock}>
              Private
            </Badge>
          )}
        </TableCell>
      )}
      <TableCell>{ccPairsIndexingStatus.docs_indexed}</TableCell>
      <TableCell>
        {isEditable && (
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div>
                  <IconButton icon={SvgSettings} tertiary />
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <Text inverted>Manage Connector</Text>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        )}
      </TableCell>
    </TableRow>
  );
}

function FederatedConnectorRow({
  federatedConnector,
  invisible,
}: {
  federatedConnector: FederatedConnectorStatus;
  invisible?: boolean;
}) {
  const router = useRouter();
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  const handleManageClick = (e: any) => {
    e.stopPropagation();
    router.push(`/admin/federated/${federatedConnector.id}`);
  };

  return (
    <TableRow
      className={`
  border border-border dark:border-neutral-700
          hover:bg-accent-background ${
            invisible
              ? "invisible !h-0 !-mb-10 !border-none"
              : "!border border-border dark:border-neutral-700"
          }  w-full cursor-pointer relative `}
      onClick={() => {
        router.push(`/admin/federated/${federatedConnector.id}`);
      }}
    >
      <TableCell className="">
        <p className="lg:w-[200px] xl:w-[400px] inline-block ellipsis truncate">
          {federatedConnector.name}
        </p>
      </TableCell>
      <TableCell>N/A</TableCell>
      <TableCell>
        <Badge variant="success">Indexed</Badge>
      </TableCell>
      {isPaidEnterpriseFeaturesEnabled && (
        <TableCell>
          <Badge variant="secondary" icon={FiRefreshCw}>
            Federated Access
          </Badge>
        </TableCell>
      )}
      <TableCell>N/A</TableCell>
      <TableCell>
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <FiSettings
                className="cursor-pointer"
                onClick={handleManageClick}
              />
            </TooltipTrigger>
            <TooltipContent>
              <p>Manage Federated Connector</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </TableCell>
    </TableRow>
  );
}

export function CCPairIndexingStatusTable({
  ccPairsIndexingStatuses,
  connectorsToggled,
  toggleSource,
  onPageChange,
  sourceLoadingStates = {} as Record<ValidSources, boolean>,
}: {
  ccPairsIndexingStatuses: ConnectorIndexingStatusLiteResponse[];
  connectorsToggled: Record<ValidSources, boolean>;
  toggleSource: (source: ValidSources, toggled?: boolean | null) => void;
  onPageChange: (source: ValidSources, newPage: number) => void;
  sourceLoadingStates?: Record<ValidSources, boolean>;
}) {
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  return (
    <Table className="-mt-8">
      <TableHeader>
        <ConnectorRow
          invisible
          ccPairsIndexingStatus={{
            cc_pair_id: 1,
            name: "Sample File Connector",
            cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
            last_status: "success",
            source: ValidSources.File,
            access_type: "public",
            docs_indexed: 1000,
            last_success: "2023-07-01T12:00:00Z",
            last_finished_status: "success",
            is_editable: false,
            in_repeated_error_state: false,
            in_progress: false,
            latest_index_attempt_docs_indexed: 0,
          }}
          isEditable={false}
        />
      </TableHeader>
      <TableBody>
        {ccPairsIndexingStatuses.map((ccPairStatus) => (
          <React.Fragment key={ccPairStatus.source}>
            <br className="mt-4 dark:bg-neutral-700" />
            <SummaryRow
              source={ccPairStatus.source}
              summary={ccPairStatus.summary}
              isOpen={connectorsToggled[ccPairStatus.source] || false}
              onToggle={() => toggleSource(ccPairStatus.source)}
            />
            {connectorsToggled[ccPairStatus.source] && (
              <>
                {sourceLoadingStates[ccPairStatus.source] && (
                  <ConnectorStaggeredSkeleton rowCount={8} height="h-[79px]" />
                )}
                {!sourceLoadingStates[ccPairStatus.source] && (
                  <>
                    <TableRow className="border border-border dark:border-neutral-700">
                      <TableHead>Name</TableHead>
                      <TableHead>Last Indexed</TableHead>
                      <TableHead>Status</TableHead>
                      {isPaidEnterpriseFeaturesEnabled && (
                        <TableHead>Permissions / Access</TableHead>
                      )}
                      <TableHead>Total Docs</TableHead>
                      <TableHead></TableHead>
                    </TableRow>
                    {ccPairStatus.indexing_statuses.map((indexingStatus) => {
                      if (isFederatedConnectorStatus(indexingStatus)) {
                        const status =
                          indexingStatus as FederatedConnectorStatus;
                        return (
                          <FederatedConnectorRow
                            key={status.id}
                            federatedConnector={status}
                          />
                        );
                      } else {
                        const status =
                          indexingStatus as ConnectorIndexingStatusLite;
                        return (
                          <ConnectorRow
                            key={status.cc_pair_id}
                            ccPairsIndexingStatus={status}
                            isEditable={status.is_editable}
                          />
                        );
                      }
                    })}
                    {/* Add dummy rows to reach 10 total rows for cleaner UI */}
                    {ccPairStatus.indexing_statuses.length <
                      NUMBER_OF_ROWS_PER_PAGE &&
                      ccPairStatus.total_pages > 1 &&
                      Array.from({
                        length:
                          NUMBER_OF_ROWS_PER_PAGE -
                          ccPairStatus.indexing_statuses.length,
                      }).map((_, index) => {
                        const isLastDummyRow =
                          index ===
                          NUMBER_OF_ROWS_PER_PAGE -
                            ccPairStatus.indexing_statuses.length -
                            1;
                        return (
                          <TableRow
                            key={`dummy-${ccPairStatus.source}-${index}`}
                            className={
                              isLastDummyRow
                                ? "border-l border-r border-b border-border dark:border-neutral-700"
                                : "border-l border-r border-t-0 border-b-0 border-border dark:border-neutral-700"
                            }
                            style={
                              isLastDummyRow
                                ? {
                                    borderBottom: "1px solid var(--border)",
                                    borderRight: "1px solid var(--border)",
                                    borderLeft: "1px solid var(--border)",
                                  }
                                : {}
                            }
                          >
                            {isLastDummyRow ? (
                              <TableCell
                                colSpan={
                                  isPaidEnterpriseFeaturesEnabled
                                    ? NUMBER_OF_COLUMNS
                                    : NUMBER_OF_COLUMNS - 1
                                }
                                className="h-[56px] text-center text-sm text-gray-400 dark:text-gray-500 border-b border-r border-l border-border dark:border-neutral-700"
                              >
                                <span className="italic">
                                  All caught up! No more connectors to show
                                </span>
                              </TableCell>
                            ) : (
                              <>
                                <TableCell className="h-[56px]"></TableCell>
                                <TableCell></TableCell>
                                <TableCell></TableCell>
                                {isPaidEnterpriseFeaturesEnabled && (
                                  <TableCell></TableCell>
                                )}
                                <TableCell></TableCell>
                                <TableCell></TableCell>
                              </>
                            )}
                          </TableRow>
                        );
                      })}
                  </>
                )}
                {ccPairStatus.total_pages > 1 && (
                  <TableRow className="border-l border-r border-b border-border dark:border-neutral-700">
                    <TableCell
                      colSpan={
                        isPaidEnterpriseFeaturesEnabled
                          ? NUMBER_OF_COLUMNS
                          : NUMBER_OF_COLUMNS - 1
                      }
                    >
                      <div className="flex justify-center">
                        <PageSelector
                          currentPage={ccPairStatus.current_page}
                          totalPages={ccPairStatus.total_pages}
                          onPageChange={(newPage) =>
                            onPageChange(ccPairStatus.source, newPage)
                          }
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                )}
              </>
            )}
          </React.Fragment>
        ))}
      </TableBody>
    </Table>
  );
}
