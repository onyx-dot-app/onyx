export function formatCurrency(amountDollars: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(amountDollars);
}

export function formatCurrencyFromCents(cents: number): string {
  return formatCurrency(cents / 100);
}

export function formatTokenCount(tokens: number): string {
  return new Intl.NumberFormat("en-US").format(tokens);
}
