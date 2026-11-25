import { render, screen, waitFor } from "@tests/setup/test-utils";
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
