import { useCallback, useEffect, useState, useRef, useMemo } from "react";
import { usePathname, useRouter } from "next/navigation";

interface PaginatedApiResponse<T> {
  items: T[];
  total_items: number;
}

interface PaginationConfig<T> {
  itemsPerPage: number;
  pagesPerBatch: number;
  endpoint: string;
  query?: string;
  filter?: Record<string, string | boolean | number | string[]>;
  refreshIntervalInMs?: number;
}

interface PaginatedHookReturnData<T> {
  currentPageData: T[] | null;
  isLoading: boolean;
  error: Error | null;
  currentPage: number;
  totalPages: number;
  goToPage: (page: number) => void;
  refresh: () => Promise<void>;
  hasNoData: boolean;
}

export function usePaginatedData<T>({
  itemsPerPage,
  pagesPerBatch,
  endpoint,
  query,
  filter,
  refreshIntervalInMs = 5000,
}: PaginationConfig<T>): PaginatedHookReturnData<T> {
  const router = useRouter();

  const [currentPage, setCurrentPage] = useState(() => {
    if (typeof window !== "undefined") {
      const urlParams = new URLSearchParams(window.location.search);
      return parseInt(urlParams.get("page") || "1", 10);
    }
    return 1;
  });
  const [currentPageData, setCurrentPageData] = useState<T[] | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [cachedBatches, setCachedBatches] = useState<{ [key: number]: T[][] }>(
    {}
  );
  const [totalItems, setTotalItems] = useState<number>(0);

  const ongoingRequestsRef = useRef<Set<number>>(new Set());

  const totalPages = useMemo(() => {
    if (totalItems === 0) return 1;
    return Math.ceil(totalItems / itemsPerPage);
  }, [totalItems, itemsPerPage]);

  const currentBatchInfo = useMemo(() => {
    const batchNum = Math.floor((currentPage - 1) / pagesPerBatch);
    const batchPageNum = (currentPage - 1) % pagesPerBatch;
    return { batchNum, batchPageNum };
  }, [currentPage, pagesPerBatch]);

  const hasNoData = useMemo(() => {
    return (
      Object.keys(cachedBatches).length === 0 ||
      Object.values(cachedBatches).every((batch) =>
        batch.every((page) => page.length === 0)
      )
    );
  }, [cachedBatches]);

  const currentPath = usePathname();

  // Batch fetching logic
  const fetchBatchData = useCallback(
    async (batchNum: number) => {
      if (ongoingRequestsRef.current.has(batchNum)) {
        return;
      }
      ongoingRequestsRef.current.add(batchNum);

      try {
        const params = new URLSearchParams({
          page: (batchNum + 1).toString(),
          page_size: (pagesPerBatch * itemsPerPage).toString(),
        });

        if (query) params.set("q", query);

        if (filter) {
          console.log("filter in usePaginatedData", filter);
          for (const [key, value] of Object.entries(filter)) {
            if (Array.isArray(value)) {
              console.log("value in roles array in usePaginatedData", value);
              value.forEach((str) => params.append(key, str));
            } else {
              params.set(key, value.toString());
            }
          }
        }
        // Log the full URL that will be fetched
        console.log("Fetching URL:", `${endpoint}?${params.toString()}`);
        // Or log just the params
        console.log("URL Parameters:", Object.fromEntries(params.entries()));

        const response = await fetch(`${endpoint}?${params.toString()}`);
        if (!response.ok) throw new Error("Failed to fetch data");
        const responseData: PaginatedApiResponse<T> = await response.json();

        const data = responseData.items;
        const totalCount = responseData.total_items;

        if (totalCount !== undefined) {
          setTotalItems(totalCount);
        }

        const newBatchData = Array.from({ length: pagesPerBatch }, (_, i) => {
          const startIndex = i * itemsPerPage;
          return data.slice(startIndex, startIndex + itemsPerPage);
        });

        setCachedBatches((prev) => ({
          ...prev,
          [batchNum]: newBatchData,
        }));
      } catch (error) {
        setError(
          error instanceof Error ? error : new Error("Error fetching data")
        );
      } finally {
        ongoingRequestsRef.current.delete(batchNum);
      }
    },
    [endpoint, pagesPerBatch, itemsPerPage, query, filter]
  );

  const updatePageUrl = useCallback(
    (page: number) => {
      if (currentPath) {
        router.replace(`${currentPath}?page=${page}`, { scroll: false });
        window.scrollTo({ top: 0, left: 0, behavior: "smooth" });
      }
    },
    [currentPath, router]
  );

  const goToPage = useCallback(
    (newPage: number) => {
      setCurrentPage(newPage);
      updatePageUrl(newPage);
    },
    [updatePageUrl]
  );

  // Effect to load current and adjacent batches
  useEffect(() => {
    const { batchNum } = currentBatchInfo;
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

  // Effect to update current page data from cache
  useEffect(() => {
    const { batchNum, batchPageNum } = currentBatchInfo;

    if (cachedBatches[batchNum] && cachedBatches[batchNum][batchPageNum]) {
      setCurrentPageData(cachedBatches[batchNum][batchPageNum]);
      setIsLoading(false);
    }
  }, [currentPage, cachedBatches, pagesPerBatch]);

  // Effect for periodic refresh
  useEffect(() => {
    if (!refreshIntervalInMs) return;

    const interval = setInterval(() => {
      const { batchNum } = currentBatchInfo;
      fetchBatchData(batchNum);
    }, refreshIntervalInMs);

    return () => clearInterval(interval);
  }, [currentPage, pagesPerBatch, refreshIntervalInMs, fetchBatchData]);

  // Manaual refresh function
  const refresh = useCallback(async () => {
    const { batchNum } = currentBatchInfo;
    await fetchBatchData(batchNum);
  }, [currentPage, pagesPerBatch, fetchBatchData]);

  // Cache invalidation
  useEffect(() => {
    setCachedBatches({});
    setTotalItems(0);
    goToPage(1);
  }, [currentPath, query, filter]);

  return {
    currentPage,
    currentPageData,
    totalPages,
    goToPage,
    refresh,
    isLoading,
    error,
    hasNoData,
  };
}
