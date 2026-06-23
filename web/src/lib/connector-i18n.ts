import { useTranslation } from "react-i18next";
import { SourceCategory } from "@/lib/search/interfaces";

const CATEGORY_KEYS: Record<SourceCategory, string> = {
  [SourceCategory.Wiki]: "admin.connector_setup.categories.wiki",
  [SourceCategory.Storage]: "admin.connector_setup.categories.storage",
  [SourceCategory.TicketingAndTaskManagement]:
    "admin.connector_setup.categories.ticketing",
  [SourceCategory.Messaging]: "admin.connector_setup.categories.messaging",
  [SourceCategory.Sales]: "admin.connector_setup.categories.sales",
  [SourceCategory.CodeRepository]:
    "admin.connector_setup.categories.code_repository",
  [SourceCategory.Other]: "admin.connector_setup.categories.other",
};

export function useSourceCategoryLabel(category: SourceCategory): string {
  const { t } = useTranslation();
  return t(CATEGORY_KEYS[category], category);
}
