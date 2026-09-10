"use client";

import { useMemo, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { OpalStringsProvider, type OpalStrings } from "@opal/strings";
import { createLocaleIntegerParser } from "@/i18n/numbers";

interface OpalStringsBridgeProps {
  children: ReactNode;
}

/** Feeds Opal's built-in labels from the `opal` catalog namespace. */
export default function OpalStringsBridge({
  children,
}: OpalStringsBridgeProps) {
  const t = useTranslations("opal");
  const locale = useLocale();
  const strings = useMemo<OpalStrings>(() => {
    // Counts such as "1234~1250" are identifiers, so no grouping separators.
    const digits = new Intl.NumberFormat(locale, { useGrouping: false });
    return {
      close: t("common.close"),
      loading: t("common.loading"),
      loadingPage: t("common.loadingPage"),
      copy: t("common.copy"),
      copied: t("common.copied"),
      copyCode: t("common.copyCode"),
      clear: t("common.clear"),
      attachFile: t("inputFile.attachFile"),
      clearFile: t("inputFile.clearFile"),
      clearFilter: t("common.clearFilter"),
      date: t("common.date"),
      dateRange: t("dateRange.label"),
      dateRangeOneDay: t("dateRange.oneDay"),
      dateRangeSevenDays: t("dateRange.sevenDays"),
      dateRangeOneMonth: t("dateRange.oneMonth"),
      dateRangeThreeMonths: t("dateRange.threeMonths"),
      dateRangeCustom: t("dateRange.custom"),
      dateRangeChooseCustom: t("dateRange.chooseCustom"),
      dateRangeCustomRange: (from, to) =>
        t("dateRange.customRange", { from, to }),
      time: t("common.time"),
      edit: t("common.edit"),
      search: t("common.search"),
      progress: t("common.progress"),
      remove: t("common.remove"),
      removeItem: (title) => t("common.removeItem", { title }),
      showFullMessage: t("common.showFullMessage"),
      selectAnOption: t("common.selectAnOption"),
      openCalendar: t("common.openCalendar"),
      month: t("input.month"),
      day: t("input.day"),
      year: t("input.year"),
      hours: t("input.hours"),
      minutes: t("input.minutes"),
      seconds: t("input.seconds"),
      showPassword: t("input.showPassword"),
      hidePassword: t("input.hidePassword"),
      valueCannotBeRevealed: t("input.valueCannotBeRevealed"),
      scrollTabsLeft: t("tabs.scrollLeft"),
      scrollTabsRight: t("tabs.scrollRight"),
      previousPage: t("pagination.previousPage"),
      nextPage: t("pagination.nextPage"),
      goToPage: t("pagination.goToPage"),
      sort: t("table.sort"),
      sortBy: t("table.sortBy"),
      manualOrdering: t("table.manualOrdering"),
      sortingOrder: t("table.sortingOrder"),
      ascending: t("table.ascending"),
      descending: t("table.descending"),
      columns: t("table.columns"),
      shownColumns: t("table.shownColumns"),
      alwaysShown: t("table.alwaysShown"),
      dragToReorder: t("table.dragToReorder"),
      viewSelected: t("table.viewSelected"),
      deselectAll: t("table.deselectAll"),
      selectItemsToContinue: t("table.selectItemsToContinue"),
      selectAnItemToContinue: t("table.selectAnItemToContinue"),
      singleItemSelected: t("table.singleItemSelected"),
      selectedItemCount: (count) => t("table.selectedItemCount", { count }),
      keyValueKey: t("keyValue.key"),
      keyValueValue: t("keyValue.value"),
      keyValueAddLine: t("keyValue.addLine"),
      keyValueAddPair: (keyTitle, valueTitle) =>
        t("keyValue.addPair", { keyTitle, valueTitle }),
      keyValueEmpty: t("keyValue.empty"),
      keyValueEmptyKey: t("keyValue.emptyKey"),
      keyValueDuplicateKey: t("keyValue.duplicateKey"),
      keyValueEmptySummary: (count) => t("keyValue.emptySummary", { count }),
      keyValueDuplicateSummary: (count) =>
        t("keyValue.duplicateSummary", { count }),
      keyValueValidationSummary: (count) =>
        t("keyValue.validationSummary", { count }),
      keyValueGroup: (keyTitle, valueTitle) =>
        t("keyValue.group", { keyTitle, valueTitle }),
      keyValueInput: (label, index) => t("keyValue.input", { label, index }),
      keyValuePairFallback: t("keyValue.pairFallback"),
      keyValueRemovePair: (label, index) =>
        t("keyValue.removePair", { label, index }),
      formatNumber: (value) => digits.format(value),
      parseNumber: createLocaleIntegerParser(digits),
      showing: (range, total) =>
        t.rich("table.showing", { range: () => range, total: () => total }),
      rangeOfTotal: (range, total) =>
        t.rich("pagination.rangeOfTotal", {
          range: () => range,
          total: () => total,
        }),
    };
  }, [t, locale]);
  return (
    <OpalStringsProvider strings={strings}>{children}</OpalStringsProvider>
  );
}
