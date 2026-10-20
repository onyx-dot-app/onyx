/** How a locale writes amounts in one currency. */
export interface CurrencyParts {
  /** The currency symbol, e.g. "$", "€" or "US$". */
  symbol: string;
  /** The symbol follows the amount ("3,00 €") instead of leading it ("$3.00"). */
  symbolAfter: boolean;
  /** The decimal separator, e.g. "." or ",". */
  decimal: string;
  /** The currency's usual number of decimals (USD 2, JPY 0). */
  fractionDigits: number;
}

const FALLBACK_PARTS: Omit<CurrencyParts, "symbol"> = {
  symbolAfter: false,
  decimal: ".",
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
    // A zero-decimal currency writes no separator, so read it from a plain number.
    const decimal =
      new Intl.NumberFormat(locale)
        .formatToParts(1.5)
        .find((part) => part.type === "decimal")?.value ??
      FALLBACK_PARTS.decimal;
    return {
      symbol: parts[symbolIndex]?.value ?? currency,
      symbolAfter: symbolIndex > integerIndex,
      decimal,
      fractionDigits:
        format.resolvedOptions().maximumFractionDigits ??
        FALLBACK_PARTS.fractionDigits,
    };
  } catch {
    return { ...FALLBACK_PARTS, symbol: currency };
  }
}
