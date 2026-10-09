import { NextIntlClientProvider } from "next-intl";
import englishMessages from "@/i18n/messages/en.json";
import { render, screen } from "@tests/setup/test-utils";
import { CsvPreview } from "@/app/craft/components/output-panel/CsvPreview";

it("bounds the number of rendered rows", () => {
  render(
    <CsvPreview
      content={Array.from({ length: 1200 }, () => "a,b").join("\n")}
    />
  );
  expect(screen.getAllByRole("row")).toHaveLength(1000);
  expect(screen.getByText(/Preview limited/)).toBeInTheDocument();
});

it("reports malformed CSV instead of rendering a plausible partial table", () => {
  render(<CsvPreview content={'a,b\n"unfinished'} />);
  expect(screen.getByRole("alert")).toHaveTextContent("invalid quoted field");
  expect(screen.queryByRole("cell")).not.toBeInTheDocument();
});

it("formats the configured cell limit in the truncation notice", () => {
  const content = Array.from({ length: 1000 }, () =>
    Array.from({ length: 100 }, () => "value").join(",")
  ).join("\n");
  render(<CsvPreview content={content} />);
  expect(screen.getByText(/Preview limited/)).toHaveTextContent(
    "1,000 rows, 100 columns, and 5,000 cells"
  );
  expect(screen.getAllByRole("cell")).toHaveLength(4900);
});

it("uses the selected locale to format numeric preview limits", () => {
  const content = Array.from({ length: 1000 }, () =>
    Array.from({ length: 100 }, () => "value").join(",")
  ).join("\n");
  render(
    <NextIntlClientProvider locale="de" messages={englishMessages}>
      <CsvPreview content={content} />
    </NextIntlClientProvider>
  );
  expect(screen.getByText(/Preview limited/)).toHaveTextContent(
    "1.000 rows, 100 columns, and 5.000 cells"
  );
});

it("shows malformed input feedback instead of modified CSV cells", () => {
  render(<CsvPreview content={'"account"oops,balance'} />);
  expect(screen.getByRole("alert")).toHaveTextContent("invalid quoted field");
  expect(screen.queryByRole("cell")).not.toBeInTheDocument();
});
