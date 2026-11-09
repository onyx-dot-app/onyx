import { useEffect, type ReactNode } from "react";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  setupUser,
  act,
} from "@tests/setup/test-utils";
import PdfDocumentViewer from "@/app/craft/components/output-panel/PdfDocumentViewer";

const mockDocumentCallbacks: Array<{
  onLoadSuccess: (pdf: { numPages: number }) => void;
  onLoadError: () => void;
}> = [];
beforeEach(() => {
  mockDocumentCallbacks.length = 0;
});

jest.mock("react-pdf", () => ({
  pdfjs: { version: "test", GlobalWorkerOptions: {} },
  Document: ({
    children,
    file,
    onLoadSuccess,
    onLoadError,
  }: {
    children: ReactNode;
    file: Blob;
    onLoadSuccess: (pdf: { numPages: number }) => void;
    onLoadError: () => void;
  }) => {
    useEffect(() => {
      mockDocumentCallbacks.push({ onLoadSuccess, onLoadError });
      onLoadSuccess({ numPages: 3 });
    }, [file]);
    return <div>{children}</div>;
  },
  Page: ({
    pageNumber,
    scale,
    onLoadSuccess,
    onRenderSuccess,
  }: {
    pageNumber: number;
    scale?: number;
    onRenderSuccess?: () => void;
    onLoadSuccess?: (page: {
      pageNumber: number;
      getViewport: () => { width: number; height: number };
    }) => void;
  }) => {
    useEffect(() => {
      onRenderSuccess?.();
      onLoadSuccess?.({
        pageNumber,
        getViewport: () => ({ width: 612, height: 792 }),
      });
    }, [pageNumber]);
    return (
      <div
        data-testid={scale === undefined ? "thumbnail" : "pdf-page"}
        data-page={pageNumber}
        data-scale={scale}
      />
    );
  },
}));

it("navigates pages with arrows and thumbnails", async () => {
  const onPageChange = jest.fn();
  render(
    <PdfDocumentViewer
      blob={new Blob(["pdf"])}
      isActive
      onDownload={jest.fn()}
      onPageChange={onPageChange}
    />
  );
  const next = await screen.findByRole("button", { name: "Next page" });
  expect(screen.getByRole("button", { name: "Previous page" })).toBeDisabled();
  expect(
    screen.queryByRole("button", { name: /Increase|Decrease/ })
  ).not.toBeInTheDocument();
  fireEvent.click(next);
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "2");
  fireEvent.click(next);
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "3");
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
  expect(next).toBeDisabled();
  expect(onPageChange).toHaveBeenLastCalledWith(3);
  fireEvent.click(screen.getByRole("button", { name: "Go to page 1" }));
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "1");
});

it("offers fit and zoom controls and a collapsible resizeable sidebar", async () => {
  render(
    <PdfDocumentViewer
      blob={new Blob(["pdf"])}
      isActive
      onDownload={jest.fn()}
    />
  );
  const user = setupUser();
  await screen.findByRole("separator", { name: "Resize page thumbnails" });
  await user.click(screen.getByRole("button", { name: "Zoom" }));
  await user.click(screen.getByRole("option", { name: "150%" }));
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-scale", "1.5");
  await user.click(screen.getByRole("button", { name: "Zoom in" }));
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-scale", "1.75");
  await user.click(
    screen.getByRole("button", { name: "Toggle page thumbnails" })
  );
  expect(screen.queryByRole("separator")).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: "Toggle page thumbnails" })
  );
  await waitFor(() =>
    expect(screen.getByRole("separator")).toBeInTheDocument()
  );
});

// Thumbnail retention
it("retains rendered thumbnails without starting hidden page previews", async () => {
  const blob = new Blob(["pdf"]);
  const view = (isActive: boolean) => (
    <PdfDocumentViewer blob={blob} isActive={isActive} onDownload={jest.fn()} />
  );
  const { rerender } = render(view(false));
  await screen.findByTestId("pdf-page");
  expect(screen.queryAllByTestId("thumbnail")).toHaveLength(0);
  rerender(view(true));
  const thumbnail = await screen.findByTestId("thumbnail");
  rerender(view(false));
  expect(screen.getByTestId("thumbnail")).toBe(thumbnail);
  rerender(view(true));
  expect(screen.getByTestId("thumbnail")).toBe(thumbnail);
});

// Source replacement and asynchronous ownership
it("ignores retired document callbacks while retaining page and zoom preferences", async () => {
  const onPageChange = jest.fn();
  const view = (blob: Blob) => (
    <PdfDocumentViewer
      blob={blob}
      isActive
      onDownload={jest.fn()}
      onPageChange={onPageChange}
    />
  );
  const { rerender } = render(view(new Blob(["first"])));
  await screen.findByRole("button", { name: "Next page" });
  fireEvent.click(screen.getByRole("button", { name: "Next page" }));
  const user = setupUser();
  await user.click(screen.getByRole("button", { name: "Zoom" }));
  await user.click(screen.getByRole("option", { name: "150%" }));
  const retired = mockDocumentCallbacks[0];
  rerender(view(new Blob(["replacement"])));
  await screen.findByRole("button", { name: "Next page" });
  act(() => {
    retired?.onLoadSuccess({ numPages: 1 });
    retired?.onLoadError();
  });
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-page", "2");
  expect(screen.getByTestId("pdf-page")).toHaveAttribute("data-scale", "1.5");
  expect(screen.getByRole("button", { name: "Next page" })).not.toBeDisabled();
  expect(onPageChange).toHaveBeenLastCalledWith(2);
});
