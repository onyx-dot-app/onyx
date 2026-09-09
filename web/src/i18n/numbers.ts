/** Parses whole numbers typed in the digits `format` prints, so users can enter what the UI shows.
 *  ASCII digits are always accepted. */
export function createLocaleIntegerParser(
  format: Intl.NumberFormat
): (text: string) => number | null {
  const localeDigits = Array.from({ length: 10 }, (_, digit) =>
    format.format(digit)
  );
  return (text) => {
    if (text === "") return null;
    let ascii = "";
    for (const char of text) {
      const digit = localeDigits.indexOf(char);
      if (digit !== -1) {
        ascii += digit;
        continue;
      }
      if (!/^\d$/.test(char)) return null;
      ascii += char;
    }
    return Number(ascii);
  };
}
