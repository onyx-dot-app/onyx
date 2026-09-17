import { DEFAULT_LOCALE } from "@/i18n/config";

export function formatCurrency(
  amountDollars: number,
  locale: string = DEFAULT_LOCALE
): string {
  return new Intl.NumberFormat(locale, {
    style: "currency",
    currency: "USD",
  }).format(amountDollars);
}

export function formatCurrencyFromCents(
  cents: number,
  locale: string = DEFAULT_LOCALE
): string {
  return formatCurrency(cents / 100, locale);
}

export function formatTokenCount(
  tokens: number,
  locale: string = DEFAULT_LOCALE
): string {
  return new Intl.NumberFormat(locale).format(tokens);
}
