"use client";

import { createSharedHook } from "@opal/hooks";
import { useSearchFilters } from "@/lib/searchFilters/hooks";

/**
 * One search selection, shared across a tree.
 *
 * The chat input bar and the tools popover edit the same filters, and the send
 * path reads them. Without this the state has to live above all three and reach
 * the popover as a prop through `AppInputBar`, which never looks at it.
 *
 * The provider is the unit of sharing, so a modal that mounts its own gets its
 * own selection and cannot disturb the chat behind it. Anything wanting its own
 * state and no provider — the admin document explorer, for one — keeps calling
 * {@link useSearchFilters} directly.
 */
export const [SearchFiltersProvider, useSharedSearchFilters] = createSharedHook(
  useSearchFilters,
  "SearchFilters"
);
