import { SourceCategory } from "@/lib/search/interfaces";

/**
 * Message key, inside the `admin.addConnector` namespace, for each category
 * heading in the connector catalog. The enum values are identifiers shared
 * across the app, so the labels live in the catalog rather than the enum.
 */
export const SOURCE_CATEGORY_LABEL_KEYS = {
  [SourceCategory.Wiki]: "categories.wiki.label",
  [SourceCategory.Storage]: "categories.storage.label",
  [SourceCategory.TicketingAndTaskManagement]:
    "categories.ticketingAndTaskManagement.label",
  [SourceCategory.Messaging]: "categories.messaging.label",
  [SourceCategory.Sales]: "categories.sales.label",
  [SourceCategory.CodeRepository]: "categories.codeRepository.label",
  [SourceCategory.Other]: "categories.other.label",
} as const satisfies Record<SourceCategory, string>;
