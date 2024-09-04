"use client";

import { useEffect, useCallback, useRef } from "react";
import debounce from "lodash/debounce";
import {
  Table,
  TableHead,
  TableRow,
  TableHeaderCell,
  TableBody,
  TableCell,
  Text,
} from "@tremor/react";
import { CCPairFullInfo } from "./types";
import { IndexAttemptStatus } from "@/components/Status";
import { useState } from "react";
import { PageSelector } from "@/components/PageSelector";
import { ThreeDotsLoader } from "@/components/Loading";
import { buildCCPairInfoUrl } from "./lib";
import { localizeAndPrettify } from "@/lib/time";
import { getDocsProcessedPerMinute } from "@/lib/indexAttempt";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { ErrorCallout } from "@/components/ErrorCallout";
import { SearchIcon } from "@/components/icons/icons";
import Link from "next/link";
import ExceptionTraceModal from "@/components/modals/ExceptionTraceModal";
import { PaginatedIndexAttempts } from "./types";
import { useRouter } from "next/navigation";

const NUM_IN_PAGE = 8;
const PAGES_TO_PREFETCH = 20;

export function IndexingAttemptsTable({ ccPair }: { ccPair: CCPairFullInfo }) {
  const router = useRouter();
  const [page, setPage] = useState(() => {
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      return parseInt(urlParams.get("page") || "1", 10);
    }
    return 1;
  });
  const [indexAttemptTracePopupId, setIndexAttemptTracePopupId] = useState<
    number | null
  >(null);
  const [currentPageData, setCurrentPageData] =
    useState<PaginatedIndexAttempts | null>(null);
  const [currentPageError, setCurrentPageError] = useState<Error | null>(null);
  const [isCurrentPageLoading, setIsCurrentPageLoading] = useState(false);
  const [cachedPages, setCachedPages] = useState<{
    [key: number]: PaginatedIndexAttempts;
  }>({});

  const cachedPagesRef = useRef(cachedPages);
  cachedPagesRef.current = cachedPages;

  // This is used to update the current page data when the page number is clicked
  const updateCurrentPageData = useCallback((pageNum: number) => {
    if (cachedPagesRef.current[pageNum]) {
      setCurrentPageData(cachedPagesRef.current[pageNum]);
      setIsCurrentPageLoading(false);
    }
  }, []);

  const urlBuilder = (pageNum: number) =>
    `${buildCCPairInfoUrl(ccPair.id)}/index-attempts?page=${pageNum}&page_size=${NUM_IN_PAGE}`;

  // This is to prevent the same page from being fetched multiple times
  const debouncedFetch = useCallback(
    debounce((pageNum: number) => {
      const fetchCurrentPageData = async () => {
        setIsCurrentPageLoading(true);
        try {
          const response = await fetch(urlBuilder(pageNum));
          if (!response.ok) {
            throw new Error("Failed to fetch data");
          }
          const data = await response.json();
          setCurrentPageData(data);
          setCachedPages((prev) => ({ ...prev, [pageNum]: data }));
        } catch (error) {
          setCurrentPageError(
            error instanceof Error ? error : new Error("An error occurred")
          );
        } finally {
          setIsCurrentPageLoading(false);
          router.refresh();
        }
      };

      if (!cachedPagesRef.current[pageNum]) {
        fetchCurrentPageData();
      } else {
        updateCurrentPageData(pageNum);
      }

      // Prefetch logic
      const totalPages = Math.ceil(
        ccPair.number_of_index_attempts / NUM_IN_PAGE
      );
      const pagesToPrefetch = Array.from(
        { length: PAGES_TO_PREFETCH * 2 },
        (_, i) => i - PAGES_TO_PREFETCH + 1
      )
        .filter((offset) => offset !== 0)
        .map((offset) => pageNum + offset)
        .filter((p) => p > 0 && p <= totalPages && !cachedPagesRef.current[p]);

      if (pagesToPrefetch.length > 0) {
        Promise.all(
          pagesToPrefetch.map((p) => errorHandlingFetcher(urlBuilder(p)))
        ).then((results) => {
          const newCachedPages = results.reduce((acc, data, index) => {
            acc[pagesToPrefetch[index]] = data;
            return acc;
          }, {});
          setCachedPages((prev) => ({ ...prev, ...newCachedPages }));
        });
      }
    }, 200),
    [ccPair.id, ccPair.number_of_index_attempts, updateCurrentPageData]
  );

  useEffect(() => {
    updateCurrentPageData(page);
    debouncedFetch(page);
  }, [page, debouncedFetch, updateCurrentPageData]);

  const indexAttemptToDisplayTraceFor = currentPageData?.index_attempts?.find(
    (indexAttempt) => indexAttempt.id === indexAttemptTracePopupId
  );

  const updatePage = (newPage: number) => {
    setPage(newPage);
    router.push(`/admin/connector/${ccPair.id}?page=${newPage}`, {
      scroll: false,
    });
    window.scrollTo({
      top: 0,
      left: 0,
      behavior: "smooth",
    });
  };

  if (currentPageError) {
    return (
      <ErrorCallout
        errorTitle={`Failed to fetch info on Connector with ID ${ccPair.id}`}
        errorMsg={currentPageError?.toString() || "Unknown error"}
      />
    );
  }

  if (!currentPageData) {
    return <ThreeDotsLoader />;
  }

  return (
    <>
      {indexAttemptToDisplayTraceFor &&
        indexAttemptToDisplayTraceFor.full_exception_trace && (
          <ExceptionTraceModal
            onOutsideClick={() => setIndexAttemptTracePopupId(null)}
            exceptionTrace={indexAttemptToDisplayTraceFor.full_exception_trace!}
          />
        )}

      <Table>
        <TableHead>
          <TableRow>
            <TableHeaderCell>Time Started</TableHeaderCell>
            <TableHeaderCell>Status</TableHeaderCell>
            <TableHeaderCell>New Doc Cnt</TableHeaderCell>
            <TableHeaderCell>Total Doc Cnt</TableHeaderCell>
            <TableHeaderCell>Error Message</TableHeaderCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {currentPageData?.index_attempts?.map((indexAttempt) => {
            const docsPerMinute =
              getDocsProcessedPerMinute(indexAttempt)?.toFixed(2);
            return (
              <TableRow key={indexAttempt.id}>
                <TableCell>
                  {indexAttempt.time_started
                    ? localizeAndPrettify(indexAttempt.time_started)
                    : "-"}
                </TableCell>
                <TableCell>
                  <IndexAttemptStatus
                    status={indexAttempt.status || "not_started"}
                    size="xs"
                  />
                  {docsPerMinute && (
                    <div className="text-xs mt-1">
                      {docsPerMinute} docs / min
                    </div>
                  )}
                </TableCell>
                <TableCell>
                  <div className="flex">
                    <div className="text-right">
                      <div>{indexAttempt.new_docs_indexed}</div>
                      {indexAttempt.docs_removed_from_index > 0 && (
                        <div className="text-xs w-52 text-wrap flex italic overflow-hidden whitespace-normal px-1">
                          (also removed {indexAttempt.docs_removed_from_index}{" "}
                          docs that were detected as deleted in the source)
                        </div>
                      )}
                    </div>
                  </div>
                </TableCell>
                <TableCell>{indexAttempt.total_docs_indexed}</TableCell>
                <TableCell>
                  <div>
                    {indexAttempt.error_count > 0 && (
                      <Link
                        className="cursor-pointer my-auto"
                        href={`/admin/indexing/${indexAttempt.id}`}
                      >
                        <Text className="flex flex-wrap text-link whitespace-normal">
                          <SearchIcon />
                          &nbsp;View Errors
                        </Text>
                      </Link>
                    )}

                    {indexAttempt.status === "success" && (
                      <Text className="flex flex-wrap whitespace-normal">
                        {"-"}
                      </Text>
                    )}

                    {indexAttempt.status === "failed" &&
                      indexAttempt.error_msg && (
                        <Text className="flex flex-wrap whitespace-normal">
                          {indexAttempt.error_msg}
                        </Text>
                      )}

                    {indexAttempt.full_exception_trace && (
                      <div
                        onClick={() => {
                          setIndexAttemptTracePopupId(indexAttempt.id);
                        }}
                        className="mt-2 text-link cursor-pointer select-none"
                      >
                        View Full Trace
                      </div>
                    )}
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
      {currentPageData && currentPageData.total_pages > 1 && (
        <div className="mt-3 flex">
          <div className="mx-auto">
            <PageSelector
              totalPages={currentPageData.total_pages}
              currentPage={page}
              onPageChange={updatePage}
            />
          </div>
        </div>
      )}
    </>
  );
}
