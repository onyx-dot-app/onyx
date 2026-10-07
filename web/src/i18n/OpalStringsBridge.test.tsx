import { NextIntlClientProvider } from "next-intl";
import { render } from "@tests/setup/test-utils";
import Footer from "@opal/components/table/Footer";
import { runtimeLocale, type RuntimeLocale } from "@/i18n/config";
import OpalStringsBridge from "@/i18n/OpalStringsBridge";
import arabicMessages from "@/i18n/messages/ar.json";
import englishMessages from "@/i18n/messages/en.json";

type Messages = typeof englishMessages;

function renderFooterThroughBridge(locale: RuntimeLocale, messages: Messages) {
  const { container } = render(
    <NextIntlClientProvider locale={locale} messages={messages}>
      <OpalStringsBridge>
        <Footer
          mode="summary"
          rangeStart={1}
          rangeEnd={10}
          totalItems={22}
          currentPage={1}
          totalPages={3}
          onPageChange={() => {}}
          units="users"
        />
      </OpalStringsBridge>
    </NextIntlClientProvider>
  );
  const summaryRow =
    container.querySelector(".table-footer")?.firstElementChild
      ?.firstElementChild;
  if (!summaryRow) throw new Error("footer summary did not render");
  return summaryRow;
}

describe("OpalStringsBridge", () => {
  it("keeps the English footer summary as four sibling spans", () => {
    const row = renderFooterThroughBridge("en", englishMessages);
    expect(row.textContent).toBe("Showing 1~10 of 22 users");
    expect([...row.children].map((child) => child.tagName)).toEqual([
      "SPAN",
      "SPAN",
      "SPAN",
      "SPAN",
    ]);
  });

  it("splits a translated rich message into the same span layout", () => {
    const row = renderFooterThroughBridge("ar", arabicMessages);
    expect(row.textContent).toBe("عرض 1~10 من 22 users");
    expect([...row.children].map((child) => child.tagName)).toEqual([
      "SPAN",
      "SPAN",
      "SPAN",
      "SPAN",
    ]);
    expect(row.querySelector('span[dir="ltr"]')).toHaveTextContent("1~10");
  });

  it("renders the footer digits in the numbering system of the runtime locale", () => {
    const row = renderFooterThroughBridge(runtimeLocale("ar"), arabicMessages);
    expect(row.textContent).toBe("عرض ١~١٠ من ٢٢ users");
    expect(row.querySelector('span[dir="ltr"]')).toHaveTextContent("١~١٠");
  });
});
