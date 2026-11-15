/** How a locale writes amounts in one currency. */
export interface CurrencyParts {
  /** The currency symbol, e.g. "$", "€" or "US$". */
  symbol: string;
  /** The symbol follows the amount ("3,00 €") instead of leading it ("$3.00"). */
  symbolAfter: boolean;
  /** The decimal separator, e.g. "." or ",". */
  decimal: string;
  /** The grouping separator, e.g. "," in "1,200" or "." in "1.200". */
  group: string;
  /** The currency's usual number of decimals (USD 2, JPY 0). */
  fractionDigits: number;
}

const FALLBACK_PARTS: Omit<CurrencyParts, "symbol"> = {
  symbolAfter: false,
  decimal: ".",
  group: ",",
  fractionDigits: 2,
};

/**
 * Reads the symbol, symbol position, decimal separator and usual decimals of
 * `currency` (an ISO 4217 code) in `locale`. An unknown code falls back to the
 * code itself as the symbol.
 */
export function getCurrencyParts(
  locale: string,
  currency: string
): CurrencyParts {
  try {
    const format = new Intl.NumberFormat(locale, {
      style: "currency",
      currency,
    });
    const parts = format.formatToParts(1);
    const symbolIndex = parts.findIndex((part) => part.type === "currency");
    const integerIndex = parts.findIndex((part) => part.type === "integer");
    // A zero-decimal currency writes no separator, so read both separators
    // from a plain number.
    const numberParts = new Intl.NumberFormat(locale).formatToParts(1234567.5);
    const decimal =
      numberParts.find((part) => part.type === "decimal")?.value ??
      FALLBACK_PARTS.decimal;
    const group =
      numberParts.find((part) => part.type === "group")?.value ??
      FALLBACK_PARTS.group;
    return {
      symbol: parts[symbolIndex]?.value ?? currency,
      symbolAfter: symbolIndex > integerIndex,
      decimal,
      group,
      fractionDigits:
        format.resolvedOptions().maximumFractionDigits ??
        FALLBACK_PARTS.fractionDigits,
    };
  } catch {
    return { ...FALLBACK_PARTS, symbol: currency };
  }
}
