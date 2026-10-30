import { fireEvent, render, screen } from "@tests/setup/test-utils";
import UrlBar from "@/app/craft/components/output-panel/UrlBar";

jest.mock("@/app/craft/components/ShareButton", () => ({
  __esModule: true,
  default: () => null,
}));

it("keeps one leading reload and prevents repeated requests while pending", () => {
  const onRefresh = jest.fn();
  const { rerender } = render(
    <UrlBar
      displayUrl="outputs/report.md"
      onRefresh={onRefresh}
      refreshLabel="Reload file"
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Reload file" }));
  expect(onRefresh).toHaveBeenCalledTimes(1);
  rerender(
    <UrlBar
      displayUrl="outputs/report.md"
      onRefresh={onRefresh}
      refreshLabel="Reload file"
      isRefreshing
      isUserRefreshing
    />
  );
  expect(screen.getByRole("button", { name: "Reload file" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Reload file" })).toHaveAttribute(
    "aria-busy",
    "true"
  );
});

it("dims background refreshes and spins only for user reloads", () => {
  const props = { displayUrl: "", onRefresh: jest.fn(), isRefreshing: true };
  const { container, rerender } = render(<UrlBar {...props} />);
  expect(screen.getByRole("button", { name: "Refresh" })).toBeDisabled();
  expect(container.querySelector(".motion-safe\\:animate-spin")).toBeNull();
  rerender(<UrlBar {...props} isUserRefreshing />);
  expect(container.querySelector(".motion-safe\\:animate-spin")).not.toBeNull();
});

it("keeps Files search input mounted and editable when inventory refreshes", () => {
  const change = jest.fn();
  const { rerender } = render(
    <UrlBar
      displayUrl=""
      searchValue="report"
      onSearchChange={change}
      placeholder="Search files"
    />
  );
  const input = screen.getByRole("textbox", { name: "Search files" });
  input.focus();
  fireEvent.change(input, { target: { value: "reports" } });
  expect(change).toHaveBeenCalledWith("reports");
  rerender(
    <UrlBar
      displayUrl=""
      searchValue="reports"
      onSearchChange={change}
      placeholder="Search files"
      isRefreshing
    />
  );
  expect(screen.getByRole("textbox", { name: "Search files" })).toBe(input);
  expect(input).toHaveFocus();
});

it("uses original download separately from document export", () => {
  const raw = jest.fn();
  const exportFile = jest.fn();
  render(
    <UrlBar
      displayUrl="outputs/report.md"
      onDownloadRaw={raw}
      onDownload={exportFile}
    />
  );
  fireEvent.click(screen.getByRole("button", { name: "Download file" }));
  fireEvent.click(screen.getByRole("button", { name: "Export to .docx" }));
  expect(raw).toHaveBeenCalledTimes(1);
  expect(exportFile).toHaveBeenCalledTimes(1);
});
