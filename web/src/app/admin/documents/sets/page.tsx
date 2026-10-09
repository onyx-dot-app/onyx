"use client";

import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useTranslations } from "next-intl";
import { PageLoader } from "@opal/loaders";
import { PageSelector } from "@/components/PageSelector";
import {
  Table,
  TableHead,
  TableRow,
  TableBody,
  TableCell,
} from "@/components/ui/table";
import { Text } from "@opal/components";
import { escapeMarkdown, markdown, richNodes } from "@opal/utils";
import { Spacer } from "@opal/components";
import { DocumentSetSummary, FederatedConnectorSummary } from "@/lib/types";
import { useMemo, useState } from "react";
import { useDocumentSets } from "./hooks";
import { can } from "@/lib/permissions/resource-actions";
import { ConnectorTitle } from "@/components/admin/connectors/ConnectorTitle";
import { deleteDocumentSet } from "./lib";
import { IllustrationContent, SettingsLayouts, toast } from "@opal/layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import AdminListHeader from "@/sections/admin/AdminListHeader";
import HighlightedText from "@/app/admin/documents/sets/HighlightedText";
import {
  getConnectorSourceName,
  getSearchTerms,
  matchesSourceOnly,
  searchDocumentSets,
} from "@/lib/documentSets/search";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import {
  FiAlertTriangle,
  FiCheckCircle,
  FiClock,
  FiEdit2,
  FiLock,
  FiUnlock,
} from "react-icons/fi";
import { DeleteButton } from "@/components/DeleteButton";
import { useRouter } from "next/navigation";
import { TableHeader } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Tooltip } from "@opal/components";
import { SourceIcon } from "@/components/SourceIcon";
import Link from "next/link";
import { useSettings } from "@/lib/settings/hooks";

const route = ADMIN_ROUTES.DOCUMENT_SETS;

const numToDisplay = 50;

// Component to display federated connectors with consistent styling
const FederatedConnectorTitle = ({
  federatedConnector,
  terms,
  showMetadata = true,
  isLink = true,
}: {
  federatedConnector: FederatedConnectorSummary;
  terms: string[];
  showMetadata?: boolean;
  isLink?: boolean;
}) => {
  const t = useTranslations("admin.documents");
  const sourceType = federatedConnector.source.replace(/^federated_/, "");

  const mainSectionClassName = "text-blue-500 dark:text-blue-100 flex w-fit";
  const mainDisplay = (
    <>
      <SourceIcon sourceType={sourceType as any} iconSize={16} />
      <div className="ms-1 my-auto text-xs font-medium truncate">
        <HighlightedText text={federatedConnector.name} terms={terms} />
      </div>
      <Badge variant="outline" className="text-xs ms-2">
        {t("sets.federatedBadge.label")}
      </Badge>
    </>
  );

  return (
    <div className="my-auto max-w-full">
      {isLink ? (
        <Link
          className={mainSectionClassName}
          href={`/admin/federated/${federatedConnector.id}`}
        >
          {mainDisplay}
        </Link>
      ) : (
        <div className={mainSectionClassName}>{mainDisplay}</div>
      )}
      {showMetadata && Object.keys(federatedConnector.entities).length > 0 && (
        <div className="text-[10px] mt-0.5 text-gray-600 dark:text-gray-400">
          {Object.entries(federatedConnector.entities)
            .filter(
              ([_, value]) =>
                value &&
                (Array.isArray(value) ? value.length > 0 : String(value).trim())
            )
            .map(([key, value]) => (
              <div key={key} className="truncate">
                <i>{key}:</i>{" "}
                <HighlightedText
                  text={Array.isArray(value) ? value.join(", ") : String(value)}
                  terms={terms}
                />
              </div>
            ))}
        </div>
      )}
    </div>
  );
};

const EditRow = ({
  documentSet,
  isEditable,
  terms,
}: {
  documentSet: DocumentSetSummary;
  isEditable: boolean;
  terms: string[];
}) => {
  const t = useTranslations("admin.documents");
  const router = useRouter();

  if (!isEditable) {
    return (
      <div className="text-text-darker font-medium my-auto p-1">
        <HighlightedText text={documentSet.name} terms={terms} />
      </div>
    );
  }

  return (
    <div className="relative flex">
      <Tooltip
        tooltip={
          !documentSet.is_up_to_date
            ? t("sets.editRow.syncing.tooltip")
            : undefined
        }
      >
        <button
          type="button"
          className={`
              text-text-darker font-medium my-auto p-1 hover:bg-accent-background flex items-center select-none
              ${documentSet.is_up_to_date ? "cursor-pointer" : "cursor-default"}
            `}
          style={{ wordBreak: "normal", overflowWrap: "break-word" }}
          // Not `disabled`: a disabled button fires no pointer events, which
          // would hide the tooltip that explains why it cannot be used.
          aria-disabled={!documentSet.is_up_to_date}
          onClick={() => {
            if (!documentSet.is_up_to_date) return;
            router.push(`/admin/documents/sets/${documentSet.id}`);
          }}
        >
          <FiEdit2 className="me-2 shrink-0" />
          <span className="font-medium">
            <HighlightedText text={documentSet.name} terms={terms} />
          </span>
        </button>
      </Tooltip>
    </div>
  );
};

interface DocumentSetTableProps {
  /** The sets to show, already searched and ordered. */
  documentSets: DocumentSetSummary[];
  /** How many sets exist before the search. */
  totalCount: number;
  terms: string[];
  page: number;
  onPageChange: (page: number) => void;
  refresh: () => void;
}

const DocumentSetTable = ({
  documentSets,
  totalCount,
  terms,
  page,
  onPageChange,
  refresh,
}: DocumentSetTableProps) => {
  const t = useTranslations("admin.documents");
  const totalPages = Math.max(1, Math.ceil(documentSets.length / numToDisplay));
  // A page from before the search, or from before a delete, can be past the end.
  const currentPage = Math.min(page, totalPages);

  return (
    <div>
      <div className="px-4">
        <Text font="secondary-body" color="text-03">
          {documentSets.length === totalCount
            ? t("sets.resultCount.total.label", { count: totalCount })
            : t("sets.resultCount.filtered.label", {
                shown: documentSets.length,
                total: totalCount,
              })}
        </Text>
      </div>
      <Table className="overflow-visible mt-2">
        <TableHeader>
          <TableRow>
            <TableHead>{t("sets.table.name.header")}</TableHead>
            <TableHead>{t("sets.table.connectors.header")}</TableHead>
            <TableHead>{t("sets.table.status.header")}</TableHead>
            <TableHead>{t("sets.table.public.header")}</TableHead>
            <TableHead>{t("sets.table.delete.header")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {documentSets
            .slice((currentPage - 1) * numToDisplay, currentPage * numToDisplay)
            .map((documentSet) => {
              const isEditable = can(documentSet, "edit");
              return (
                <TableRow key={documentSet.id}>
                  <TableCell className="whitespace-normal break-all">
                    <div className="flex gap-x-1 text-emphasis">
                      <EditRow
                        documentSet={documentSet}
                        isEditable={isEditable}
                        terms={terms}
                      />
                    </div>
                    {documentSet.description && (
                      <div className="ps-1 break-normal">
                        <Text
                          font="secondary-body"
                          color="text-03"
                          wordWrap="wrap-break-word"
                          maxLines={2}
                        >
                          {richNodes(
                            <HighlightedText
                              text={documentSet.description}
                              terms={terms}
                            />
                          )}
                        </Text>
                      </div>
                    )}
                  </TableCell>
                  <TableCell>
                    <div>
                      {/* Regular Connectors */}
                      {documentSet.cc_pair_summaries.map(
                        (ccPairSummary, ind) => {
                          return (
                            <div
                              className={
                                ind !== documentSet.cc_pair_summaries.length - 1
                                  ? "mb-3"
                                  : ""
                              }
                              key={ccPairSummary.id}
                            >
                              <div className="text-blue-500 dark:text-blue-100 flex w-fit">
                                <SourceIcon
                                  sourceType={ccPairSummary.source}
                                  iconSize={16}
                                />
                                <div className="ms-1 my-auto text-xs font-medium truncate">
                                  {ccPairSummary.name ? (
                                    <HighlightedText
                                      text={ccPairSummary.name}
                                      terms={terms}
                                    />
                                  ) : (
                                    t("sets.connector.unnamed.label")
                                  )}
                                </div>
                              </div>
                              {/* Shows why a set matched when only the
                                  connector's source holds the term. */}
                              {matchesSourceOnly(ccPairSummary, terms) && (
                                <div className="mt-0.5 ps-5">
                                  <Text
                                    font="figure-small-value"
                                    color="text-03"
                                    wordWrap="whitespace-nowrap"
                                  >
                                    {richNodes(
                                      <HighlightedText
                                        text={getConnectorSourceName(
                                          ccPairSummary
                                        )}
                                        terms={terms}
                                      />
                                    )}
                                  </Text>
                                </div>
                              )}
                            </div>
                          );
                        }
                      )}

                      {/* Federated Connectors */}
                      {documentSet.federated_connector_summaries &&
                        documentSet.federated_connector_summaries.length >
                          0 && (
                          <>
                            {documentSet.cc_pair_summaries.length > 0 && (
                              <div className="mb-3" />
                            )}
                            {documentSet.federated_connector_summaries.map(
                              (federatedConnector, ind) => {
                                return (
                                  <div
                                    className={
                                      ind !==
                                      documentSet.federated_connector_summaries
                                        .length -
                                        1
                                        ? "mb-3"
                                        : ""
                                    }
                                    key={`federated-${federatedConnector.id}`}
                                  >
                                    <FederatedConnectorTitle
                                      federatedConnector={federatedConnector}
                                      terms={terms}
                                      showMetadata={true}
                                    />
                                  </div>
                                );
                              }
                            )}
                          </>
                        )}
                    </div>
                  </TableCell>
                  <TableCell>
                    {documentSet.is_up_to_date ? (
                      <Badge variant="success" icon={FiCheckCircle}>
                        {t("sets.status.upToDate.label")}
                      </Badge>
                    ) : documentSet.cc_pair_summaries.length > 0 ||
                      (documentSet.federated_connector_summaries &&
                        documentSet.federated_connector_summaries.length >
                          0) ? (
                      <Badge variant="in_progress" icon={FiClock}>
                        {t("sets.status.syncing.label")}
                      </Badge>
                    ) : (
                      <Badge variant="destructive" icon={FiAlertTriangle}>
                        {t("sets.status.deleting.label")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {documentSet.is_public ? (
                      <Badge
                        variant={isEditable ? "success" : "default"}
                        icon={FiUnlock}
                      >
                        {t("sets.access.public.label")}
                      </Badge>
                    ) : (
                      <Badge
                        variant={isEditable ? "private" : "default"}
                        icon={FiLock}
                      >
                        {t("sets.access.private.label")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    {can(documentSet, "delete") ? (
                      <DeleteButton
                        onClick={async () => {
                          const response = await deleteDocumentSet(
                            documentSet.id
                          );
                          if (response.ok) {
                            toast.success(
                              t("sets.deleteScheduled.toast", {
                                name: documentSet.name,
                              })
                            );
                          } else {
                            const errorMsg = (await response.json()).detail;
                            toast.error(
                              t("sets.deleteFailed.toast", { detail: errorMsg })
                            );
                          }
                          refresh();
                        }}
                      />
                    ) : (
                      "-"
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
        </TableBody>
      </Table>

      <div className="mt-3 flex">
        <div className="mx-auto">
          <PageSelector
            totalPages={totalPages}
            currentPage={currentPage}
            onPageChange={onPageChange}
          />
        </div>
      </div>
    </div>
  );
};

function Main() {
  const t = useTranslations("admin.documents");
  const { appName } = useSettings();
  const router = useRouter();
  const [searchQuery, setSearchQuery] = useState("");
  const [page, setPage] = useState(1);
  const [pageBeforeSearch, setPageBeforeSearch] = useState(1);
  const {
    data: documentSets,
    isLoading: isDocumentSetsLoading,
    error: documentSetsError,
    refreshDocumentSets,
  } = useDocumentSets();

  // editable rows first, then by name — editability now rides on each row's
  // permissions map, so no second fetch + set-diff is needed.
  const sortedDocumentSets = useMemo(
    () =>
      [...(documentSets ?? [])].sort((a, b) => {
        const editDiff = Number(can(b, "edit")) - Number(can(a, "edit"));
        return editDiff !== 0 ? editDiff : a.name.localeCompare(b.name);
      }),
    [documentSets]
  );
  const matchingDocumentSets = useMemo(
    () => searchDocumentSets(sortedDocumentSets, searchQuery),
    [sortedDocumentSets, searchQuery]
  );
  const terms = useMemo(() => getSearchTerms(searchQuery), [searchQuery]);

  // A search starts on the first page. Clearing it returns to the page the
  // admin was on before.
  function handleSearchQueryChange(query: string) {
    const wasSearching = searchQuery.trim() !== "";
    const isSearching = query.trim() !== "";
    if (isSearching) {
      if (!wasSearching) setPageBeforeSearch(page);
      setPage(1);
    } else if (wasSearching) {
      setPage(pageBeforeSearch);
    }
    setSearchQuery(query);
  }

  if (isDocumentSetsLoading) {
    return (
      <div className="flex justify-center items-center min-h-[400px]">
        <PageLoader />
      </div>
    );
  }

  if (documentSetsError || !documentSets) {
    return (
      <div>
        {t("sets.loadError.message", { detail: String(documentSetsError) })}
      </div>
    );
  }

  return (
    <div className="mb-8">
      <Text as="p">
        {markdown(t("sets.description", { appName: escapeMarkdown(appName) }))}
      </Text>
      <Spacer rem={0.75} />

      <AdminListHeader
        hasItems={documentSets.length > 0}
        searchQuery={searchQuery}
        onSearchQueryChange={handleSearchQueryChange}
        placeholder={t("sets.search.placeholder")}
        emptyStateText={t("sets.empty.text")}
        onAction={() => router.push("/admin/documents/sets/new")}
        actionLabel={t("sets.newButton.label")}
      />

      {documentSets.length > 0 &&
        (matchingDocumentSets.length > 0 ? (
          <DocumentSetTable
            documentSets={matchingDocumentSets}
            totalCount={documentSets.length}
            terms={terms}
            page={page}
            onPageChange={setPage}
            refresh={refreshDocumentSets}
          />
        ) : (
          <IllustrationContent
            illustration={SvgNoResult}
            title={t("sets.noResults.title")}
            description={t("sets.noResults.description", {
              query: searchQuery.trim(),
            })}
          />
        ))}
    </div>
  );
}

export default function Page() {
  const adminRouteTitle = useAdminRouteTitle();
  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        divider
      />
      <SettingsLayouts.Body>
        <Main />
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
