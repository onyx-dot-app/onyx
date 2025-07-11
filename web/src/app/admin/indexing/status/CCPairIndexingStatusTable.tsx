import React, { useState, useMemo, useEffect, useRef } from "react";
import {
  Table,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
  TableHeader,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CCPairStatus } from "@/components/Status";
import { timeAgo } from "@/lib/time";
import {
  ConnectorIndexingStatus,
  ConnectorSummary,
  GroupedConnectorSummaries,
  ValidSources,
  ValidStatuses,
  FederatedConnectorDetail,
  federatedSourceToRegularSource,
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
import Cookies from "js-cookie";
import { TOGGLED_CONNECTORS_COOKIE_NAME } from "@/lib/constants";
import { usePaidEnterpriseFeaturesEnabled } from "@/components/settings/usePaidEnterpriseFeaturesEnabled";
import { ConnectorCredentialPairStatus } from "../../connector/[ccPairId]/types";
import { FilterComponent, FilterOptions } from "./FilterComponent";

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
        <div className="text-xl font-semibold">{summary.count}</div>
      </TableCell>

      <TableCell>
        <div className="text-sm text-neutral-500 dark:text-neutral-300">
          Active Connectors
        </div>
        <p className="flex text-xl mx-auto font-semibold items-center text-lg mt-1">
          {summary.active}/{summary.count}
        </p>
      </TableCell>

      {isPaidEnterpriseFeaturesEnabled && (
        <TableCell>
          <div className="text-sm text-neutral-500 dark:text-neutral-300">
            Public Connectors
          </div>
          <p className="flex text-xl mx-auto font-semibold items-center text-lg mt-1">
            {summary.public}/{summary.count}
          </p>
        </TableCell>
      )}

      <TableCell>
        <div className="text-sm text-neutral-500 dark:text-neutral-300">
          Total Docs Indexed
        </div>
        <div className="text-xl font-semibold">
          {summary.totalDocsIndexed.toLocaleString()}
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
  ccPairsIndexingStatus: ConnectorIndexingStatus<any, any>;
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
          lastIndexAttemptStatus={
            ccPairsIndexingStatus.latest_index_attempt?.status
          }
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
              {getSourceDisplayName(ccPairsIndexingStatus.connector.source)}
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
                <FiSettings
                  className="cursor-pointer"
                  onClick={handleManageClick}
                />
              </TooltipTrigger>
              <TooltipContent>
                <p>Manage Connector</p>
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
  federatedConnector: FederatedConnectorDetail;
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
  editableCcPairsIndexingStatuses,
  federatedConnectors,
}: {
  ccPairsIndexingStatuses: ConnectorIndexingStatus<any, any>[];
  editableCcPairsIndexingStatuses: ConnectorIndexingStatus<any, any>[];
  federatedConnectors: FederatedConnectorDetail[];
}) {
  const [searchTerm, setSearchTerm] = useState("");

  const searchInputRef = useRef<HTMLInputElement>(null);
  const isPaidEnterpriseFeaturesEnabled = usePaidEnterpriseFeaturesEnabled();

  useEffect(() => {
    if (searchInputRef.current) {
      searchInputRef.current.focus();
    }
  }, []);

  const [connectorsToggled, setConnectorsToggled] = useState<
    Record<ValidSources, boolean>
  >(() => {
    const savedState = Cookies.get(TOGGLED_CONNECTORS_COOKIE_NAME);
    return savedState ? JSON.parse(savedState) : {};
  });

  const [filterOptions, setFilterOptions] = useState<FilterOptions>({
    accessType: null,
    docsCountFilter: {
      operator: null,
      value: null,
    },
    lastStatus: null,
  });

  // Reference to the FilterComponent for resetting its state
  const filterComponentRef = useRef<{
    resetFilters: () => void;
  } | null>(null);

  const {
    groupedStatuses,
    sortedSources,
    groupSummaries,
    filteredGroupedStatuses,
  } = useMemo(() => {
    const grouped: Record<ValidSources, ConnectorIndexingStatus<any, any>[]> =
      {} as Record<ValidSources, ConnectorIndexingStatus<any, any>[]>;

    // First, add editable connectors
    editableCcPairsIndexingStatuses.forEach((status) => {
      const source = status.connector.source;
      if (!grouped[source]) {
        grouped[source] = [];
      }
      grouped[source].unshift(status);
    });

    // Then, add non-editable connectors
    ccPairsIndexingStatuses.forEach((status) => {
      const source = status.connector.source;
      if (!grouped[source]) {
        grouped[source] = [];
      }
      if (
        !editableCcPairsIndexingStatuses.some(
          (e) => e.cc_pair_id === status.cc_pair_id
        )
      ) {
        grouped[source].push(status);
      }
    });

    const sorted = Object.keys(grouped).sort() as ValidSources[];

    const summaries: GroupedConnectorSummaries =
      {} as GroupedConnectorSummaries;
    sorted.forEach((source) => {
      const statuses = grouped[source];
      const federatedForSource = federatedConnectors.filter(
        (fc) => federatedSourceToRegularSource(fc.source) === source
      );

      summaries[source] = {
        count: statuses.length + federatedForSource.length,
        active:
          statuses.filter(
            (status) =>
              status.cc_pair_status === ConnectorCredentialPairStatus.ACTIVE
          ).length + federatedForSource.length, // All federated connectors are considered active
        public: statuses.filter((status) => status.access_type === "public")
          .length,
        totalDocsIndexed: statuses.reduce(
          (sum, status) => sum + status.docs_indexed,
          0
        ),
        errors: statuses.filter(
          (status) => status.last_finished_status === "failed"
        ).length,
      };
    });

    // Apply filters to create filtered grouped statuses
    const filteredGrouped: Record<
      ValidSources,
      ConnectorIndexingStatus<any, any>[]
    > = {} as Record<ValidSources, ConnectorIndexingStatus<any, any>[]>;

    sorted.forEach((source) => {
      const statuses = grouped[source];

      // Apply filters
      const filteredStatuses = statuses.filter((status) => {
        // Filter by access type
        if (filterOptions.accessType && filterOptions.accessType.length > 0) {
          if (!filterOptions.accessType.includes(status.access_type)) {
            return false;
          }
        }

        // Filter by last status
        if (filterOptions.lastStatus && filterOptions.lastStatus.length > 0) {
          if (
            !filterOptions.lastStatus.includes(
              status.last_status as ValidStatuses
            )
          ) {
            return false;
          }
        }

        // Filter by docs count
        if (filterOptions.docsCountFilter.operator) {
          const { operator, value } = filterOptions.docsCountFilter;

          // If only operator is selected (no value), show all
          if (value === null) {
            return true;
          }

          if (operator === ">" && !(status.docs_indexed > value)) {
            return false;
          } else if (operator === "<" && !(status.docs_indexed < value)) {
            return false;
          } else if (operator === "=" && status.docs_indexed !== value) {
            return false;
          }
        }

        return true;
      });

      if (filteredStatuses.length > 0) {
        filteredGrouped[source] = filteredStatuses;
      }
    });

    return {
      groupedStatuses: grouped,
      sortedSources: sorted,
      groupSummaries: summaries,
      filteredGroupedStatuses: filteredGrouped,
    };
  }, [ccPairsIndexingStatuses, editableCcPairsIndexingStatuses, filterOptions]);

  // Combine regular connector sources with sources that only have federated connectors
  const allSourcesWithFederated = useMemo(() => {
    const federatedSources = Array.from(
      new Set(
        federatedConnectors.map((fc) =>
          federatedSourceToRegularSource(fc.source)
        )
      )
    ) as ValidSources[];

    // Ensure we keep original ordering for existing sources, then append any new ones
    const combined = [...sortedSources];
    federatedSources.forEach((src) => {
      if (!combined.includes(src)) {
        combined.push(src);
      }
    });

    return combined;
  }, [sortedSources, federatedConnectors]);

  // Determine which sources to display based on filters and search
  const displaySources = useMemo(() => {
    const hasActiveFilters =
      (filterOptions.accessType && filterOptions.accessType.length > 0) ||
      (filterOptions.lastStatus && filterOptions.lastStatus.length > 0) ||
      filterOptions.docsCountFilter.operator !== null;

    if (hasActiveFilters) {
      return Object.keys(filteredGroupedStatuses) as ValidSources[];
    }

    return allSourcesWithFederated;
  }, [allSourcesWithFederated, filteredGroupedStatuses, filterOptions]);

  const handleFilterChange = (newFilters: FilterOptions) => {
    setFilterOptions(newFilters);

    // Auto-expand sources when filters are applied
    if (
      (newFilters.accessType && newFilters.accessType.length > 0) ||
      (newFilters.lastStatus && newFilters.lastStatus.length > 0) ||
      newFilters.docsCountFilter.operator !== null
    ) {
      // We need to wait for the filteredGroupedStatuses to be updated
      // before we can expand the sources
      setTimeout(() => {
        const sourcesToExpand = Object.keys(
          filteredGroupedStatuses
        ) as ValidSources[];
        const newConnectorsToggled = { ...connectorsToggled };

        sourcesToExpand.forEach((source) => {
          newConnectorsToggled[source] = true;
        });

        setConnectorsToggled(newConnectorsToggled);
        Cookies.set(
          TOGGLED_CONNECTORS_COOKIE_NAME,
          JSON.stringify(newConnectorsToggled)
        );
      }, 0);
    }
  };

  // Check if filters are active
  const hasActiveFilters = useMemo(() => {
    return (
      (filterOptions.accessType && filterOptions.accessType.length > 0) ||
      (filterOptions.lastStatus && filterOptions.lastStatus.length > 0) ||
      filterOptions.docsCountFilter.operator !== null
    );
  }, [filterOptions]);

  const toggleSource = (
    source: ValidSources,
    toggled: boolean | null = null
  ) => {
    const newConnectorsToggled = {
      ...connectorsToggled,
      [source]: toggled == null ? !connectorsToggled[source] : toggled,
    };
    setConnectorsToggled(newConnectorsToggled);
    Cookies.set(
      TOGGLED_CONNECTORS_COOKIE_NAME,
      JSON.stringify(newConnectorsToggled)
    );
  };

  const toggleSources = () => {
    const connectors = sortedSources.reduce(
      (acc, source) => {
        acc[source] = shouldExpand;
        return acc;
      },
      {} as Record<ValidSources, boolean>
    );

    setConnectorsToggled(connectors);
    Cookies.set(TOGGLED_CONNECTORS_COOKIE_NAME, JSON.stringify(connectors));
  };

  const shouldExpand =
    Object.values(connectorsToggled).filter(Boolean).length <
    sortedSources.length;

  return (
    <>
      <Table>
        <TableHeader>
          <ConnectorRow
            invisible
            ccPairsIndexingStatus={{
              cc_pair_id: 1,
              name: "Sample File Connector",
              cc_pair_status: ConnectorCredentialPairStatus.ACTIVE,
              last_status: "success",
              connector: {
                name: "Sample File Connector",
                source: ValidSources.File,
                input_type: "poll",
                connector_specific_config: {
                  file_locations: ["/path/to/sample/file.txt"],
                  zip_metadata: {},
                },
                refresh_freq: 86400,
                prune_freq: null,
                indexing_start: new Date("2023-07-01T12:00:00Z"),
                id: 1,
                credential_ids: [],
                access_type: "public",
                time_created: "2023-07-01T12:00:00Z",
                time_updated: "2023-07-01T12:00:00Z",
              },
              credential: {
                id: 1,
                name: "Sample Credential",
                source: ValidSources.File,
                user_id: "1",
                user_email: "sample@example.com",
                time_created: "2023-07-01T12:00:00Z",
                time_updated: "2023-07-01T12:00:00Z",
                credential_json: {},
                admin_public: false,
              },
              access_type: "public",
              docs_indexed: 1000,
              last_success: "2023-07-01T12:00:00Z",
              last_finished_status: "success",
              latest_index_attempt: null,
              groups: [], // Add this line
              in_repeated_error_state: false,
            }}
            isEditable={false}
          />
        </TableHeader>
        <div className="flex -mt-12 items-center w-0 m4 gap-x-2">
          <input
            type="text"
            ref={searchInputRef}
            placeholder="Search connectors..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="ml-1 w-96 h-9 border border-border flex-none rounded-md bg-background-50 px-3 py-1 text-sm shadow-sm transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
          />

          <Button className="h-9" onClick={() => toggleSources()}>
            {!shouldExpand ? "Collapse All" : "Expand All"}
          </Button>

          <div className="flex items-center gap-2">
            <FilterComponent
              onFilterChange={handleFilterChange}
              ref={filterComponentRef}
            />

            {hasActiveFilters && (
              <div className="flex flex-none items-center gap-1 ml-2 max-w-[500px]">
                {filterOptions.accessType &&
                  filterOptions.accessType.length > 0 && (
                    <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                      Access: {filterOptions.accessType.join(", ")}
                    </Badge>
                  )}

                {filterOptions.lastStatus &&
                  filterOptions.lastStatus.length > 0 && (
                    <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                      Status:{" "}
                      {filterOptions.lastStatus
                        .map((s) => s.replace(/_/g, " "))
                        .join(", ")}
                    </Badge>
                  )}

                {filterOptions.docsCountFilter.operator &&
                  filterOptions.docsCountFilter.value !== null && (
                    <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                      Docs {filterOptions.docsCountFilter.operator}{" "}
                      {filterOptions.docsCountFilter.value}
                    </Badge>
                  )}

                {filterOptions.docsCountFilter.operator &&
                  filterOptions.docsCountFilter.value === null && (
                    <Badge variant="secondary" className="px-2 py-0.5 text-xs">
                      Docs {filterOptions.docsCountFilter.operator} any
                    </Badge>
                  )}

                <Badge
                  variant="outline"
                  className="px-2 py-0.5 text-xs border-red-400  bg-red-100 hover:border-red-600 cursor-pointer hover:bg-red-100 dark:hover:bg-red-900"
                  onClick={() => {
                    if (filterComponentRef.current) {
                      filterComponentRef.current.resetFilters();
                      setFilterOptions({
                        accessType: null,
                        docsCountFilter: {
                          operator: null,
                          value: null,
                        },
                        lastStatus: null,
                      });
                    }
                  }}
                >
                  <span className="text-red-500 dark:text-red-400">Clear</span>
                </Badge>
              </div>
            )}
          </div>
        </div>
        <TableBody>
          {displaySources
            .filter(
              (source) =>
                source != "not_applicable" && source != "ingestion_api"
            )
            .map((source, ind) => {
              const sourceMatches = source
                .toLowerCase()
                .includes(searchTerm.toLowerCase());

              const statuses =
                filteredGroupedStatuses[source] ??
                groupedStatuses[source] ??
                [];

              const matchingConnectors = statuses.filter((status) =>
                (status.name || "")
                  .toLowerCase()
                  .includes(searchTerm.toLowerCase())
              );

              const federatedForSource = federatedConnectors.filter(
                (fc) => federatedSourceToRegularSource(fc.source) === source
              );

              const hasFederatedMatches = federatedForSource.some((fc) =>
                fc.name.toLowerCase().includes(searchTerm.toLowerCase())
              );

              if (
                sourceMatches ||
                matchingConnectors.length > 0 ||
                hasFederatedMatches
              ) {
                const summaryForSource = groupSummaries[source] ?? {
                  count: federatedForSource.length,
                  active: federatedForSource.length, // All federated connectors are considered active
                  public: 0,
                  totalDocsIndexed: 0,
                  errors: 0,
                };
                return (
                  <React.Fragment key={ind}>
                    <br className="mt-4" />
                    <SummaryRow
                      source={source}
                      summary={summaryForSource}
                      isOpen={connectorsToggled[source] || false}
                      onToggle={() => toggleSource(source)}
                    />
                    {connectorsToggled[source] && (
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
                        {(sourceMatches ? statuses : matchingConnectors).map(
                          (ccPairsIndexingStatus) => (
                            <ConnectorRow
                              key={ccPairsIndexingStatus.cc_pair_id}
                              ccPairsIndexingStatus={ccPairsIndexingStatus}
                              isEditable={editableCcPairsIndexingStatuses.some(
                                (e) =>
                                  e.cc_pair_id ===
                                  ccPairsIndexingStatus.cc_pair_id
                              )}
                            />
                          )
                        )}

                        {/* Add federated connectors belonging to this source */}
                        {(sourceMatches
                          ? federatedForSource
                          : federatedForSource.filter((fc) =>
                              fc.name
                                .toLowerCase()
                                .includes(searchTerm.toLowerCase())
                            )
                        ).map((federatedConnector) => (
                          <FederatedConnectorRow
                            key={`federated-${federatedConnector.id}`}
                            federatedConnector={federatedConnector}
                          />
                        ))}
                      </>
                    )}
                  </React.Fragment>
                );
              }
              return null;
            })}
        </TableBody>
      </Table>
    </>
  );
}
