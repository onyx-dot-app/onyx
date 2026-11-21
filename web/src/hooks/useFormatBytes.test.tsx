import type { ReactNode } from "react";
import { renderHook } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { useFormatBytes } from "@/hooks/useFormatBytes";

function formatterFor(locale: "en" | "de"): (bytes: number) => string {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <NextIntlClientProvider locale={locale} messages={{}}>
        {children}
      </NextIntlClientProvider>
    );
  }
  return renderHook(() => useFormatBytes(), { wrapper: Wrapper }).result
    .current;
}

describe("useFormatBytes", () => {
  it("formats sizes in English", () => {
    const formatBytes = formatterFor("en");
    expect(formatBytes(500)).toBe("500 byte");
    expect(formatBytes(1023)).toBe("1,023 byte");
    expect(formatBytes(1024)).toBe("1 kB");
    expect(formatBytes(1234.5 * 1024)).toBe("1.2 MB");
    expect(formatBytes(1023.5 * 1024)).toBe("1,023.5 kB");
    expect(formatBytes(2.5 * 1024 ** 4)).toBe("2.5 TB");
    expect(formatBytes(2048 * 1024 ** 4)).toBe("2,048 TB");
  });

  it("formats sizes in German, with its separators and unit labels", () => {
    const formatBytes = formatterFor("de");
    expect(formatBytes(500)).toBe("500 Byte");
    expect(formatBytes(1023.5 * 1024)).toBe("1.023,5 kB");
    expect(formatBytes(1.5 * 1024 ** 2)).toBe("1,5 MB");
  });
});
