// TODO: check scroll behavior

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
  refreshInterval?: number;
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
  refreshInterval = 5000,
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
      console.log("fetchBatchData called with batchNum:", batchNum);

      if (ongoingRequestsRef.current.has(batchNum)) {
        console.log("Already fetching batch:", batchNum);
        return;
      }
      ongoingRequestsRef.current.add(batchNum);

      try {
        const params = {
          page: (batchNum + 1).toString(),
          page_size: (pagesPerBatch * itemsPerPage).toString(),
        } as Record<string, string>;

        if (query) params.q = query;

        const queryString = new URLSearchParams(params).toString();

        const response = await fetch(`${endpoint}?${queryString}`);
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
    [endpoint, pagesPerBatch, itemsPerPage, query]
  );

  const goToPage = useCallback(
    (newPage: number) => {
      setCurrentPage(newPage);

      if (currentPath) {
        router.replace(`${currentPath}?page=${newPage}`, { scroll: false });
        // remove if we dont want it to jump to top
        // and check pageSelector component for the rest of page adjustment logic
        window.scrollTo({ top: 0, left: 0, behavior: "smooth" });
      }
    },
    [currentPath, router]
  );

  // Loads current and adjacent batches
  useEffect(() => {
    const { batchNum } = currentBatchInfo;
    console.log("--- Effect triggered ---");
    console.log("currentPage:", currentPage);
    console.log("pagesPerBatch:", pagesPerBatch);
    console.log("Initial batchNum calculation:", batchNum);

    if (!cachedBatches[batchNum]) {
      console.log("Fetching current batch:", batchNum);
      setIsLoading(true);
      fetchBatchData(batchNum);
    }

    const nextBatchNum = batchNum + 1;
    console.log("nextBatchNum:", nextBatchNum);

    const prevBatchNum = Math.max(batchNum - 1, 0);
    console.log("prevBatchNum:", prevBatchNum);

    if (!cachedBatches[nextBatchNum]) {
      console.log("Fetching next batch:", nextBatchNum);
      fetchBatchData(nextBatchNum);
    }
    if (!cachedBatches[prevBatchNum]) {
      console.log("Fetching prev batch:", prevBatchNum);
      fetchBatchData(prevBatchNum);
    }
    if (!cachedBatches[1]) {
      console.log("Fetching batch 1");
      fetchBatchData(1);
    }

    console.log("Current cachedBatches:", cachedBatches);
    console.log("--- Effect end ---");
  }, [currentPage, cachedBatches, totalPages, pagesPerBatch, fetchBatchData]);

  // Updates current page data from cache
  useEffect(() => {
    const { batchNum, batchPageNum } = currentBatchInfo;

    if (cachedBatches[batchNum] && cachedBatches[batchNum][batchPageNum]) {
      setCurrentPageData(cachedBatches[batchNum][batchPageNum]);
      setIsLoading(false);
    } else {
      setIsLoading(true);
    }
  }, [currentPage, cachedBatches, pagesPerBatch]);

  // Manages periodic refresh
  useEffect(() => {
    if (!refreshInterval) return;

    const interval = setInterval(() => {
      const { batchNum } = currentBatchInfo;
      fetchBatchData(batchNum);
    }, refreshInterval);

    return () => clearInterval(interval);
  }, [currentPage, pagesPerBatch, refreshInterval, fetchBatchData]);

  // Manaual refresh function
  const refresh = useCallback(async () => {
    const { batchNum } = currentBatchInfo;
    await fetchBatchData(batchNum);
  }, [currentPage, pagesPerBatch, fetchBatchData]);

  // Reset state when path changes
  useEffect(() => {
    setCurrentPage(1);
    setCachedBatches({});
  }, [currentPath]);

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
