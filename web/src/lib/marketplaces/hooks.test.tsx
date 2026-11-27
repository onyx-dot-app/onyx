import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { renderHook } from "@testing-library/react";
import englishMessages from "@/i18n/messages/en.json";
import { useMarketplaceCopy } from "@/lib/marketplaces/hooks";
import { summaryFixture } from "@/sections/marketplaces/__fixtures__/marketplace";

const LOCAL_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
// next-intl formats in the server's zone. Any zone far from the local one shows a missing override.
const SERVER_ZONE =
  LOCAL_ZONE === "Pacific/Kiritimati" ? "Etc/GMT+12" : "Pacific/Kiritimati";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider
      locale="en"
      messages={englishMessages}
      timeZone={SERVER_ZONE}
    >
      {children}
    </NextIntlClientProvider>
  );
}

describe("useMarketplaceCopy", () => {
  it("shows GitHub's rate-limit reset time in the browser's zone", () => {
    const resetAt = new Date(2027, 0, 15, 9, 0);
    const { result } = renderHook(() => useMarketplaceCopy(), { wrapper });

    const text = result.current.syncError(
      summaryFixture({
        last_error: "It resets at 07:38 UTC.",
        last_error_code: "RATE_LIMITED",
        last_error_reset_at: resetAt.toISOString(),
      })
    );

    expect(text).toContain("9:00");
    expect(text).not.toContain("UTC");
  });
});
