import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import userEvent from "@testing-library/user-event";
import {
  RUN_STEP_LIST_MAX_HEIGHT_CLASS,
  RunCard,
} from "@/lib/timeline/components/RunCard";
import { RunStep } from "@/lib/timeline/components/RunStep";
import type { TimelineEntryStatus } from "@/lib/timeline/types";

interface Step {
  id: string;
  status: TimelineEntryStatus;
}

const steps: Step[] = [
  { id: "a", status: "done" },
  { id: "b", status: "done" },
];

function renderRun() {
  return render(
    <RunCard
      steps={steps}
      workingText="Working"
      durationSeconds={3}
      renderStep={(step) => (
        <RunStep
          id={step.id}
          status={step.status}
          title={`Step ${step.id}`}
          body={<p>{`Body ${step.id}`}</p>}
        />
      )}
    />
  );
}

test("a step keeps its open state when the run card folds and reopens", async () => {
  const user = userEvent.setup();
  renderRun();
  const card = screen.getByRole("button", { name: /Worked for/ });

  await user.click(card);
  await user.click(await screen.findByRole("button", { name: /Step a/ }));
  expect(await screen.findByText("Body a")).toBeInTheDocument();

  await user.click(card);
  await waitFor(() =>
    expect(screen.queryByText("Step a")).not.toBeInTheDocument()
  );

  await user.click(card);
  expect(await screen.findByText("Body a")).toBeInTheDocument();
  expect(screen.queryByText("Body b")).not.toBeInTheDocument();
});

test("the open run card's step list scrolls inside a capped height", async () => {
  const user = userEvent.setup();
  renderRun();

  await user.click(screen.getByRole("button", { name: /Worked for/ }));

  const step = await screen.findByText("Step a");
  expect(step.closest(".overflow-y-auto")).toHaveClass(
    RUN_STEP_LIST_MAX_HEIGHT_CLASS
  );
});

test("a settled card that takes over an open step mounts open, also under text", async () => {
  render(
    <RunCard
      steps={steps}
      workingText="Working"
      durationSeconds={3}
      isActive={false}
      autoCollapse
      appear={false}
      startOpen
      stepOpenState={{ openIds: new Set(["b"]), setOpen: () => {} }}
      renderStep={(step) => (
        <RunStep
          id={step.id}
          status={step.status}
          title={`Step ${step.id}`}
          body={<p>{`Body ${step.id}`}</p>}
        />
      )}
    />
  );
  expect(await screen.findByText("Body b")).toBeInTheDocument();
});

test("a scroll that the browser clamps at the end keeps the list following", async () => {
  // jsdom never resizes: the test calls the list's observer itself.
  let resized = () => {};
  jest.spyOn(global, "ResizeObserver").mockImplementation((callback) => {
    resized = () => callback([], {} as ResizeObserver);
    return {
      observe: () => {},
      unobserve: () => {},
      disconnect: () => {},
    } as unknown as ResizeObserver;
  });
  try {
    render(
      <RunCard
        steps={steps}
        workingText="Working"
        isActive
        renderStep={(step) => (
          <RunStep
            id={step.id}
            status={step.status}
            title={`Step ${step.id}`}
          />
        )}
      />
    );
    const list = (await screen.findByText("Step a")).closest(
      ".overflow-y-auto"
    );
    if (!(list instanceof HTMLElement)) throw new Error("no step list");
    let scrollHeight = 500;
    Object.defineProperty(list, "clientHeight", { value: 100 });
    Object.defineProperty(list, "scrollHeight", { get: () => scrollHeight });
    // At the end; then a row closes and the browser clamps the scroll down.
    list.scrollTop = 400;
    fireEvent.scroll(list);
    scrollHeight = 300;
    list.scrollTop = 200;
    fireEvent.scroll(list);

    // The content grows: the list follows it to the end.
    scrollHeight = 600;
    resized();
    expect(list.scrollTop).toBe(600);
  } finally {
    jest.restoreAllMocks();
  }
});

test("closing a step at the end of a short list follows new steps again", async () => {
  // Titles observe their size too, so every observer is called.
  const observers: ResizeObserverCallback[] = [];
  const resized = () =>
    observers.forEach((callback) => callback([], {} as ResizeObserver));
  jest.spyOn(global, "ResizeObserver").mockImplementation((callback) => {
    observers.push(callback);
    return {
      observe: () => {},
      unobserve: () => {},
      disconnect: () => {},
    } as unknown as ResizeObserver;
  });
  try {
    const user = userEvent.setup();
    render(
      <RunCard
        steps={steps}
        workingText="Working"
        isActive
        renderStep={(step) => (
          <RunStep
            id={step.id}
            status={step.status}
            title={`Step ${step.id}`}
            body={<p>{`Body ${step.id}`}</p>}
          />
        )}
      />
    );
    const row = await screen.findByRole("button", { name: /Step a/ });
    const list = row.closest(".overflow-y-auto");
    if (!(list instanceof HTMLElement)) throw new Error("no step list");
    // The list is below its height cap: it has no room to scroll.
    let scrollHeight = 100;
    Object.defineProperty(list, "clientHeight", { value: 100 });
    Object.defineProperty(list, "scrollHeight", { get: () => scrollHeight });

    await user.click(row);
    await user.click(row);
    expect(row).toHaveAttribute("aria-expanded", "false");

    // New steps grow past the cap: the list follows them.
    scrollHeight = 600;
    resized();
    expect(list.scrollTop).toBe(600);
  } finally {
    jest.restoreAllMocks();
  }
});
