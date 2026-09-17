// `suppressed` keeps the trigger mounted and shows nothing on hover. The
// trigger must also forget the hover, so that lifting the suppression later
// does not reveal a tooltip for a pointer that has moved on.
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { useState } from "react";
import { render, screen, userEvent, waitFor } from "@tests/setup/test-utils";
import { Tooltip } from "@opal/components";

/** Opens on the first hover, so tests do not wait out the default delay. */
function Harness({ suppressed }: { suppressed: boolean }) {
  return (
    <TooltipPrimitive.Provider delayDuration={0}>
      <Tooltip tooltip="Rename" suppressed={suppressed}>
        <button>Trigger</button>
      </Tooltip>
    </TooltipPrimitive.Provider>
  );
}

it("shows the tooltip on hover", async () => {
  const user = userEvent.setup();
  render(<Harness suppressed={false} />);

  await user.hover(screen.getByRole("button", { name: "Trigger" }));

  await waitFor(() => {
    expect(screen.getByRole("tooltip")).toBeInTheDocument();
  });
});

it("shows nothing on hover while suppressed", async () => {
  const user = userEvent.setup();
  render(<Harness suppressed />);

  await user.hover(screen.getByRole("button", { name: "Trigger" }));

  await waitFor(() => {
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});

it("does not reveal a hover the pointer already left when suppression lifts", async () => {
  const user = userEvent.setup();

  function ToggleHarness() {
    const [suppressed, setSuppressed] = useState(true);
    return (
      <>
        <Harness suppressed={suppressed} />
        <button onClick={() => setSuppressed(false)}>Unsuppress</button>
      </>
    );
  }

  render(<ToggleHarness />);

  const trigger = screen.getByRole("button", { name: "Trigger" });
  await user.hover(trigger);
  await user.unhover(trigger);

  await user.click(screen.getByRole("button", { name: "Unsuppress" }));

  await waitFor(() => {
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
