"use client";

import { Fragment } from "react";
import { useFormatter, useTranslations } from "next-intl";
import type { Period } from "@/lib/spendingLimits/types";

const CENTS_PER_DOLLAR = 100;
const TOKENS_PER_THOUSAND = 1000;

/** The budgets of one limit, in the units the API stores. */
export interface LimitAmounts {
  period: Period;
  costCents: number | null;
  tokenThousands: number | null;
}

/** Classes for the amounts inside a Text. A nested Text would add its own
 *  inline padding around each amount. */
export const EMPHASIS = {
  title: "font-main-ui-action text-text-04",
  titleInactive: "font-main-ui-action text-text-02",
  secondary: "font-secondary-action text-text-03",
} as const;
type Emphasis = (typeof EMPHASIS)[keyof typeof EMPHASIS];

/** Renders limits as "$200 or 100K tokens / week • …", with the amounts set
 *  in `emphasis` and the rest inheriting the surrounding Text. */
export function useLimitSummary() {
  const t = useTranslations("admin.spendingLimits.card.summary");
  const format = useFormatter();

  return function summarize(
    limits: LimitAmounts[],
    emphasis: Emphasis
  ): React.ReactNode {
    const b = (chunks: React.ReactNode) => (
      <span className={emphasis}>{chunks}</span>
    );
    return limits.map((limit, index) => {
      const values = {
        cost:
          limit.costCents === null
            ? ""
            : format.number(limit.costCents / CENTS_PER_DOLLAR, {
                style: "currency",
                currency: "USD",
                maximumFractionDigits: 2,
                minimumFractionDigits: 0,
              }),
        tokens:
          limit.tokenThousands === null
            ? ""
            : format.number(limit.tokenThousands * TOKENS_PER_THOUSAND, {
                notation: "compact",
              }),
        period: t(`period.${limit.period}`),
        b,
      };
      const key =
        limit.costCents !== null && limit.tokenThousands !== null
          ? "both"
          : limit.costCents !== null
            ? "cost"
            : "tokens";
      return (
        <Fragment key={index}>
          {index > 0 && t("separator")}
          {t.rich(key, values)}
        </Fragment>
      );
    });
  };
}
