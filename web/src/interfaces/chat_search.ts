/**
 * Visibility status of a chat session.
 */
export enum ChatSessionSharedStatus {
  Private = "private",
  Public = "public",
}

/**
 * Summary representation of a chat session returned from the search API.
 */
export interface ChatSessionSummary {
  /** Unique identifier for the chat session */
  id: string;
  /** Display name of the chat, or null if unnamed */
  name: string | null;
  /** ID of the persona/assistant used in this chat */
  persona_id: number | null;
  /** ISO timestamp of when the chat was created */
  time_created: string;
  /** Whether the chat is private or publicly shared */
  shared_status: ChatSessionSharedStatus;
  /** Override model being used, if different from default */
  current_alternate_model: string | null;
  /** Override temperature setting, if different from default */
  current_temperature_override: number | null;
  /** Highlighted text snippets from search matches */
  highlights?: string[];
}

/**
 * A group of chat sessions organized under a common title (e.g., "Today", "Yesterday").
 */
export interface ChatSessionGroup {
  /** Group heading displayed in the UI */
  title: string;
  /** Chat sessions belonging to this group */
  chats: ChatSessionSummary[];
}

/**
 * Paginated response from the chat search API.
 */
export interface ChatSearchResponse {
  /** Chat sessions organized into time-based groups */
  groups: ChatSessionGroup[];
  /** Whether more results are available */
  has_more: boolean;
  /** Page number for fetching the next set of results, or null if no more pages */
  next_page: number | null;
}

/**
 * Simplified chat representation used for filtering and display in the command menu.
 */
export interface FilterableChat {
  /** Unique identifier for the chat */
  id: string;
  /** Display label (chat name or fallback) */
  label: string;
  /** ISO timestamp used for sorting */
  time: string;
}

/**
 * Configuration options for the useChatSearchOptimistic hook.
 */
export interface UseChatSearchOptimisticOptions {
  /** The search query string to filter chats */
  searchQuery: string;
  /** Whether the hook should actively fetch data (defaults to true) */
  enabled?: boolean;
}

/**
 * Return value from the useChatSearchOptimistic hook.
 */
export interface UseChatSearchOptimisticResult {
  /** Filtered chat results matching the search query */
  results: FilterableChat[];
  /** True while the initial search request is in flight */
  isSearching: boolean;
  /** Whether more results can be loaded */
  hasMore: boolean;
  /** Function to load the next page of results */
  fetchMore: () => Promise<void>;
  /** True while loading additional pages */
  isLoadingMore: boolean;
  /** Ref to attach to a sentinel element for infinite scroll */
  sentinelRef: React.RefObject<HTMLDivElement | null>;
}
