import { useCallback, useEffect, useState, useRef, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  IndexAttemptSnapshot,
  AcceptedUserSnapshot,
  InvitedUserSnapshot,
} from "@/lib/types";
import { ChatSessionMinimal } from "@/app/ee/admin/performance/usage/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { PaginatedIndexAttemptErrors } from "@/app/admin/connector/[ccPairId]/types";

// Any type that has an id property
type PaginatedType = {
  id: number | string;
  [key: string]: any;
};

interface PaginatedApiResponse<T extends PaginatedType> {
  items: T[];
  total_items: number;
}

interface PaginationConfig {
  itemsPerPage: number;
  pagesPerBatch: number;
  endpoint: string;
  query?: string;
  filter?: Record<string, string | boolean | number | string[] | Date>;
  refreshIntervalInMs?: number;
  zeroIndexed?: boolean; // Flag to indicate if backend uses zero-indexed pages
}

interface PaginatedHookReturnData<T extends PaginatedType> {
  currentPageData: T[] | null;
  isLoading: boolean;
  error: Error | null;
  currentPage: number;
  totalPages: number;
  goToPage: (page: number) => void;
  refresh: () => Promise<void>;
}

function usePaginatedFetch<T extends PaginatedType>({
  itemsPerPage,
  pagesPerBatch,
  endpoint,
  query,
  filter,
  refreshIntervalInMs = 5000,
  zeroIndexed = true, // Default to true for zero-indexed pages
}: PaginationConfig): PaginatedHookReturnData<T> {
  const router = useRouter();
  const currentPath = usePathname();
  const searchParams = useSearchParams();

  // State to initialize and hold the current page number
  const [currentPage, setCurrentPage] = useState(() => {
    const urlPage = parseInt(searchParams?.get("page") || "1", 10);
    // For URL display we use 1-indexed, but for internal state we use the appropriate index based on API
    return zeroIndexed ? urlPage - 1 : urlPage;
  });
  const [currentPageData, setCurrentPageData] = useState<T[] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [totalItems, setTotalItems] = useState<number>(0);
  const [cachedBatches, setCachedBatches] = useState<{ [key: number]: T[][] }>(
    {}
  );

  // Tracks ongoing requests to avoid duplicate requests, uses ref to persist across renders
  const ongoingRequestsRef = useRef<Set<number>>(new Set());

  const totalPages = useMemo(() => {
    if (totalItems === 0) return 1;
    return Math.ceil(totalItems / itemsPerPage);
  }, [totalItems, itemsPerPage]);

  // Calculates which batch we're in, and which page within that batch
  const batchAndPageIndices = useMemo(() => {
    const pageForCalc = zeroIndexed ? currentPage : currentPage - 1;
    const batchNum = Math.floor(pageForCalc / pagesPerBatch);
    const batchPageNum = pageForCalc % pagesPerBatch;
    return { batchNum, batchPageNum };
  }, [currentPage, pagesPerBatch, zeroIndexed]);

  // Fetches a batch of data and stores it in the cache
  const fetchBatchData = useCallback(
    async (batchNum: number) => {
      // Prevents duplicate requests
      if (ongoingRequestsRef.current.has(batchNum)) {
        return;
      }
      ongoingRequestsRef.current.add(batchNum);

      try {
        // Build query params - use zero-based indexing for backend
        const params = new URLSearchParams({
          page_num: (batchNum * pagesPerBatch).toString(),
          page_size: (pagesPerBatch * itemsPerPage).toString(),
        });

        if (query) params.set("q", query);

        if (filter) {
          for (const [key, value] of Object.entries(filter)) {
            if (Array.isArray(value)) {
              value.forEach((str) => params.append(key, str));
            } else {
              params.set(key, value.toString());
            }
          }
        }

        const url = `${endpoint}?${params.toString()}`;
        const responseData =
          await errorHandlingFetcher<PaginatedApiResponse<T>>(url);

        // Validate response data structure
        if (
          !Array.isArray(
            responseData.items || typeof responseData.total_items !== "number"
          )
        ) {
          throw new Error(
            "Sorry, we encountered an issue with the data format. Please try again or contact support if the problem persists."
          );
        }

        setTotalItems(responseData.total_items);

        // Splits a batch into pages
        const pagesInBatch = Array.from({ length: pagesPerBatch }, (_, i) => {
          const startIndex = i * itemsPerPage;
          return responseData.items.slice(
            startIndex,
            startIndex + itemsPerPage
          );
        });

        setCachedBatches((prev) => ({
          ...prev,
          [batchNum]: pagesInBatch,
        }));
      } catch (error) {
        setError(error instanceof Error ? error : new Error(String(error)));
      } finally {
        ongoingRequestsRef.current.delete(batchNum);
      }
    },
    [endpoint, pagesPerBatch, itemsPerPage, query, filter]
  );

  // Updates the URL with the current page number (always 1-indexed for URL)
  const updatePageUrl = useCallback(
    (page: number) => {
      if (currentPath) {
        const params = new URLSearchParams(searchParams);
        // For URL display we always use 1-indexed
        const urlPage = zeroIndexed ? page + 1 : page;
        params.set("page", urlPage.toString());
        router.replace(`${currentPath}?${params.toString()}`, {
          scroll: false,
        });
      }
    },
    [currentPath, router, searchParams, zeroIndexed]
  );

  // Updates the current page
  const goToPage = useCallback(
    (newPage: number) => {
      // Ensure page is within bounds
      const boundedPage = Math.max(0, Math.min(newPage, totalPages - 1));
      setCurrentPage(boundedPage);
      updatePageUrl(boundedPage);
    },
    [updatePageUrl, totalPages]
  );

  // Loads the current and adjacent batches
  useEffect(() => {
    const { batchNum } = batchAndPageIndices;
    const nextBatchNum = batchNum + 1;
    const prevBatchNum = Math.max(batchNum - 1, 0);

    if (!cachedBatches[batchNum]) {
      setIsLoading(true);
      fetchBatchData(batchNum);
    }

    // Possible total number of items including the next batch
    const totalItemsIncludingNextBatch =
      nextBatchNum * pagesPerBatch * itemsPerPage;
    // Preload next batch if we're not on the last batch
    if (
      totalItemsIncludingNextBatch <= totalItems &&
      !cachedBatches[nextBatchNum]
    ) {
      fetchBatchData(nextBatchNum);
    }

    // Load previous batch if missing
    if (!cachedBatches[prevBatchNum]) {
      fetchBatchData(prevBatchNum);
    }

    // Ensure first batch is always loaded
    if (!cachedBatches[0]) {
      fetchBatchData(0);
    }
  }, [
    currentPage,
    cachedBatches,
    totalPages,
    pagesPerBatch,
    fetchBatchData,
    batchAndPageIndices,
  ]);

  // Updates current page data from the cache
  useEffect(() => {
    const { batchNum, batchPageNum } = batchAndPageIndices;

    if (cachedBatches[batchNum] && cachedBatches[batchNum][batchPageNum]) {
      setCurrentPageData(cachedBatches[batchNum][batchPageNum]);
      setIsLoading(false);
    }
  }, [currentPage, cachedBatches, pagesPerBatch, batchAndPageIndices]);

  // Implements periodic refresh
  useEffect(() => {
    if (!refreshIntervalInMs) return;

    const interval = setInterval(() => {
      const { batchNum } = batchAndPageIndices;
      fetchBatchData(batchNum);
    }, refreshIntervalInMs);

    return () => clearInterval(interval);
  }, [
    currentPage,
    pagesPerBatch,
    refreshIntervalInMs,
    fetchBatchData,
    batchAndPageIndices,
  ]);

  // Manually refreshes the current batch
  const refresh = useCallback(async () => {
    const { batchNum } = batchAndPageIndices;
    await fetchBatchData(batchNum);
  }, [batchAndPageIndices, fetchBatchData]);

  // Cache invalidation
  useEffect(() => {
    setCachedBatches({});
    setTotalItems(0);
    // Start at page 0 for zero-indexed APIs, page 1 for one-indexed
    goToPage(zeroIndexed ? 0 : 1);
    setError(null);
  }, [currentPath, query, filter, zeroIndexed, goToPage]);

  return {
    currentPage,
    currentPageData,
    totalPages,
    goToPage,
    refresh,
    isLoading,
    error,
  };
}

export default usePaginatedFetch;
