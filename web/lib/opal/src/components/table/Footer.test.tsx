import { render } from "@tests/setup/test-utils";
import Footer from "@opal/components/table/Footer";
import { OpalStringsProvider, defaultOpalStrings } from "@opal/strings";
import type { OpalStrings } from "@opal/strings";

function renderSummaryFooter(strings: OpalStrings = defaultOpalStrings) {
  const { container } = render(
    <OpalStringsProvider strings={strings}>
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
    </OpalStringsProvider>
  );
  const footer = container.querySelector(".table-footer");
  if (!footer) throw new Error("footer did not render");
  // The left side holds the summary row first, then any extra action.
  const summaryRow = footer.firstElementChild?.firstElementChild;
  return {
    summary: summaryRow?.textContent ?? "",
    // Every chunk is its own span, which is what keeps the spacing stable.
    spanCount: summaryRow?.children.length ?? 0,
    range: footer.querySelector('span[dir="ltr"]'),
  };
}

describe("Footer summary", () => {
  it("renders the English summary with the range in an LTR isolate", () => {
    const { summary, spanCount, range } = renderSummaryFooter();
    expect(summary).toBe("Showing 1~10 of 22 users");
    expect(spanCount).toBe(4);
    expect(range).toHaveTextContent("1~10");
  });

  it("renders a translated summary around the same styled nodes", () => {
    const { summary, spanCount, range } = renderSummaryFooter({
      ...defaultOpalStrings,
      showing: (range, total) => ["عرض ", range, " من ", total],
    });
    expect(summary).toBe("عرض 1~10 من 22 users");
    expect(spanCount).toBe(4);
    expect(range).toHaveTextContent("1~10");
  });
});
