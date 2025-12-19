import { useCallback, useEffect, useState, useRef, useMemo } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import { errorHandlingFetcher } from "@/lib/fetcher";

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
}

interface PaginatedHookReturnData<T extends PaginatedType> {
  currentPageData: T[] | null;
  isLoading: boolean;
  error: Error | null;
  currentPage: number;
  totalPages: number;
  totalItems: number;
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
}: PaginationConfig): PaginatedHookReturnData<T> {
  const router = useRouter();
  const currentPath = usePathname();
  const searchParams = useSearchParams();

  // State to initialize and hold the current page number
  const [currentPage, setCurrentPage] = useState(() =>
    parseInt(searchParams?.get("page") || "1", 10)
  );
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
    const batchNum = Math.floor((currentPage - 1) / pagesPerBatch);
    const batchPageNum = (currentPage - 1) % pagesPerBatch;
    return { batchNum, batchPageNum };
  }, [currentPage, pagesPerBatch]);

  // Fetches a batch of data and stores it in the cache
  const fetchBatchData = useCallback(
    async (batchNum: number) => {
      // Prevents duplicate requests
      if (ongoingRequestsRef.current.has(batchNum)) {
        return;
      }
      ongoingRequestsRef.current.add(batchNum);

      try {
        // Build query params
        const params = new URLSearchParams({
          page_num: batchNum.toString(),
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

  // Updates the URL with the current page number
  const updatePageUrl = useCallback(
    (page: number) => {
      if (currentPath && searchParams) {
        const params = new URLSearchParams(searchParams);
        params.set("page", page.toString());
        router.replace(`${currentPath}?${params.toString()}`, {
          scroll: false,
        });
      }
    },
    [currentPath, router, searchParams]
  );

  // Updates the current page
  const goToPage = useCallback(
    (newPage: number) => {
      setCurrentPage(newPage);
      updatePageUrl(newPage);
    },
    [updatePageUrl]
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
  }, [currentPage, cachedBatches, totalPages, pagesPerBatch, fetchBatchData]);

  // Updates current page data from the cache
  useEffect(() => {
    const { batchNum, batchPageNum } = batchAndPageIndices;

    const cachedBatch = cachedBatches[batchNum];
    if (cachedBatch !== undefined) {
      const cachedBatchPage = cachedBatch[batchPageNum];
      if (cachedBatchPage !== undefined) {
        setCurrentPageData(cachedBatchPage);
        setIsLoading(false);
      }
    }
  }, [currentPage, cachedBatches, pagesPerBatch]);

  // Implements periodic refresh
  useEffect(() => {
    if (!refreshIntervalInMs) return;

    const interval = setInterval(() => {
      const { batchNum } = batchAndPageIndices;
      fetchBatchData(batchNum);
    }, refreshIntervalInMs);

    return () => clearInterval(interval);
  }, [currentPage, pagesPerBatch, refreshIntervalInMs, fetchBatchData]);

  // Manually refreshes the current batch
  const refresh = useCallback(async () => {
    const { batchNum } = batchAndPageIndices;
    await fetchBatchData(batchNum);
  }, [currentPage, pagesPerBatch, fetchBatchData]);

  // Cache invalidation
  useEffect(() => {
    setCachedBatches({});
    setTotalItems(0);
    goToPage(1);
    setError(null);
  }, [currentPath, query, filter]);

  return {
    currentPage,
    currentPageData,
    totalPages,
    totalItems,
    goToPage,
    refresh,
    isLoading,
    error,
  };
}

export default usePaginatedFetch;
