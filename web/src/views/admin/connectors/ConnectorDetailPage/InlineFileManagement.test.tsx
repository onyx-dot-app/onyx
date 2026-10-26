import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import InlineFileManagement from "@/views/admin/connectors/ConnectorDetailPage/InlineFileManagement";
import {
  CONNECTOR_FILES_PAGE_SIZE,
  type ConnectorFileInfo,
} from "@/lib/fileConnector";

const CONNECTOR_ID = 7;
const TOTAL_FILES = 1000;

/** The page of a 1000-file connector that the endpoint would return. */
function filesPage(pageNum: number): ConnectorFileInfo[] {
  const start = pageNum * CONNECTOR_FILES_PAGE_SIZE;
  return Array.from({ length: CONNECTOR_FILES_PAGE_SIZE }, (_, index) => ({
    file_id: `file-${start + index}`,
    file_name: `file-${start + index}.txt`,
    file_size: 10,
  }));
}

function mockFilesEndpoint(): jest.SpyInstance {
  return jest.spyOn(global, "fetch").mockImplementation((input) => {
    const pageNum = Number(
      new URL(String(input), "http://localhost").searchParams.get("page_num") ??
        0
    );
    return Promise.resolve({
      ok: true,
      status: 200,
      json: async () => ({
        files: filesPage(pageNum),
        total_items: TOTAL_FILES,
      }),
    } as Response);
  });
}

/**
 * The pager's arrows are icon-only and Opal gives them a tooltip rather than
 * an accessible name, so they are reached by position: the pager is the last
 * thing the component renders, as `< 1 >`.
 */
function nextPageButton(): HTMLElement {
  const buttons = screen.getAllByRole("button");
  const next = buttons[buttons.length - 1]!;
  expect(buttons[buttons.length - 2]).toHaveTextContent("1");
  return next;
}

afterEach(() => {
  jest.restoreAllMocks();
});

test("lists one page of files and counts every file in the connector", async () => {
  mockFilesEndpoint();

  render(
    <InlineFileManagement connectorId={CONNECTOR_ID} onRefresh={jest.fn()} />
  );

  // The first page is listed; the file after it is not rendered at all.
  expect(await screen.findByText("file-0.txt")).toBeInTheDocument();
  expect(
    screen.getByText(`file-${CONNECTOR_FILES_PAGE_SIZE - 1}.txt`)
  ).toBeInTheDocument();
  expect(
    screen.queryByText(`file-${CONNECTOR_FILES_PAGE_SIZE}.txt`)
  ).not.toBeInTheDocument();

  // The header and the pager count the connector, not the open page.
  expect(screen.getByText("Files (1,000 files)")).toBeInTheDocument();
  expect(
    screen.getByText(`1~${CONNECTOR_FILES_PAGE_SIZE}`)
  ).toBeInTheDocument();
});

test("asks the server for one page, then for the next one", async () => {
  const user = setupUser();
  const fetchSpy = mockFilesEndpoint();

  render(
    <InlineFileManagement connectorId={CONNECTOR_ID} onRefresh={jest.fn()} />
  );
  await screen.findByText("file-0.txt");

  const firstUrl = String(fetchSpy.mock.calls[0]?.[0]);
  expect(firstUrl).toContain("page_num=0");
  expect(firstUrl).toContain(`page_size=${CONNECTOR_FILES_PAGE_SIZE}`);

  await user.click(nextPageButton());

  await waitFor(() => {
    expect(
      screen.getByText(`file-${CONNECTOR_FILES_PAGE_SIZE}.txt`)
    ).toBeInTheDocument();
  });
  // The page it left is gone from the DOM, not merely hidden.
  expect(screen.queryByText("file-0.txt")).not.toBeInTheDocument();
  expect(
    fetchSpy.mock.calls.some((call) => String(call[0]).includes("page_num=1"))
  ).toBe(true);
});

test("counts removals against the connector, not the open page", async () => {
  const user = setupUser();
  mockFilesEndpoint();

  render(
    <InlineFileManagement connectorId={CONNECTOR_ID} onRefresh={jest.fn()} />
  );
  await screen.findByText("file-0.txt");

  await user.click(screen.getByTestId("file-manager-edit"));
  const checkboxes = await screen.findAllByRole("checkbox");
  await user.click(checkboxes[0]!);

  // One file of a thousand is marked, so the count drops by one and saving
  // is allowed — the "cannot remove every file" guard counts the connector.
  expect(screen.getByText("Files (999 files)")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /save changes/i }));
  expect(
    await screen.findByRole("dialog", { name: /confirm file changes/i })
  ).toBeInTheDocument();
});
