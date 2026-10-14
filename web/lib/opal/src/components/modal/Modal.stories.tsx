import { useState } from "react";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { BasicModalFooter, Button, Modal, Tabs, Text } from "@opal/components";
import { SvgSettings, SvgTrash } from "@opal/icons";

const meta: Meta<typeof Modal.Content> = {
  title: "opal/components/Modal",
  component: Modal.Content,
  tags: ["autodocs"],
};

export default meta;
type Story = StoryObj<typeof Modal.Content>;

function ModalHarness({
  children,
  label = "Open modal",
}: {
  children: (close: () => void) => React.ReactNode;
  label?: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>{label}</Button>
      <Modal open={open} onOpenChange={setOpen}>
        {children(() => setOpen(false))}
      </Modal>
    </>
  );
}

export const Default: Story = {
  render: () => (
    <ModalHarness>
      {(close) => (
        <Modal.Content width="md">
          <Modal.Header
            icon={SvgSettings}
            title="Modal title"
            description="Supporting description for the modal."
            onClose={close}
          />
          <Modal.Body>Body content lives here.</Modal.Body>
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button prominence="secondary" onClick={close}>
                  Cancel
                </Button>
              }
              submit={<Button onClick={close}>Confirm</Button>}
            />
          </Modal.Footer>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

export const MinimalHeader: Story = {
  render: () => (
    <ModalHarness label="Open preview modal">
      {(close) => (
        <Modal.Content width="sm">
          <Modal.Header title="Preview" onClose={close} />
          <Modal.Body twoTone={false}>
            Minimal header variant without an icon.
          </Modal.Body>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

export const DangerFooter: Story = {
  render: () => (
    <ModalHarness label="Open delete modal">
      {(close) => (
        <Modal.Content width="sm">
          <Modal.Header
            icon={SvgTrash}
            title="Delete item"
            description="This cannot be undone."
            onClose={close}
          />
          <Modal.Footer>
            <BasicModalFooter
              cancel={
                <Button prominence="secondary" onClick={close}>
                  Cancel
                </Button>
              }
              submit={
                <Button variant="danger" onClick={close}>
                  Delete
                </Button>
              }
            />
          </Modal.Footer>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

export const TopPosition: Story = {
  render: () => (
    <ModalHarness label="Open top-pinned modal">
      {(close) => (
        <Modal.Content width="md" position="top">
          <Modal.Header title="Command palette position" onClose={close} />
          <Modal.Body>Pinned near the top of the viewport.</Modal.Body>
        </Modal.Content>
      )}
    </ModalHarness>
  ),
};

function AnimatedHeightPreview({
  initialTab = "short",
  height = "fit",
  bottomSlot = false,
  position = "center",
}: {
  initialTab?: string;
  height?: "fit" | "full";
  bottomSlot?: boolean;
  position?: "center" | "top";
}) {
  const [tab, setTab] = useState(initialTab);
  const [spacious, setSpacious] = useState(false);
  return (
    <ModalHarness label="Open animated modal">
      {(close) => (
        <Modal.Content
          width="md"
          height={height}
          position={position}
          bottomSlot={
            bottomSlot ? (
              <Text>Supporting content stays outside the card.</Text>
            ) : undefined
          }
        >
          <Modal.Header
            icon={SvgSettings}
            title="Connection setup"
            onClose={close}
          />
          <Modal.Body
            animateHeight
            alignItems="stretch"
            padding={spacious ? 8 : 4}
          >
            <Tabs value={tab} onValueChange={setTab}>
              <Tabs.List>
                <Tabs.Trigger value="short">Automatic</Tabs.Trigger>
                <Tabs.Trigger value="medium">Custom</Tabs.Trigger>
                <Tabs.Trigger value="long">Long content</Tabs.Trigger>
              </Tabs.List>
              <Tabs.Content value="short">
                <Text>Use the settings provided by the server.</Text>
              </Tabs.Content>
              <Tabs.Content value="medium">
                <Text>
                  Enter your own settings. These additional fields change the
                  modal height without scaling the text.
                </Text>
                <Text>
                  Content can arrive after loading or change when you switch a
                  tab.
                </Text>
                <Text>The footer remains available while the body grows.</Text>
              </Tabs.Content>
              <Tabs.Content value="long">
                <div className="flex flex-col gap-4">
                  {Array.from({ length: 30 }, (_, index) => (
                    <Text key={index}>
                      Custom configuration details stay at their natural size
                      while the modal grows. Long content scrolls inside the
                      body.
                    </Text>
                  ))}
                </div>
              </Tabs.Content>
            </Tabs>
          </Modal.Body>
          <Modal.Footer>
            <Button
              prominence="secondary"
              onClick={() => setSpacious(!spacious)}
            >
              Change spacing
            </Button>
            <Button onClick={close}>Done</Button>
          </Modal.Footer>
        </Modal.Content>
      )}
    </ModalHarness>
  );
}

export const AnimatedHeight: Story = {
  render: () => <AnimatedHeightPreview />,
};

async function settleLayout() {
  const start = performance.now();
  while (performance.now() - start < 280) {
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve())
    );
  }
}

/** Browser assertions exercise layout, which jsdom cannot measure. */
async function verifyAnimatedHeight() {
  const page = within(document.body);
  await userEvent.click(
    page.getByRole("button", { name: "Open animated modal" })
  );
  const dialog = page.getByRole("dialog");
  const body = dialog.querySelector(".opal-modal-body");
  if (!(body instanceof HTMLElement)) throw new Error("Modal body missing");
  await settleLayout();
  const tabs = page.getByRole("tablist");
  const initialWidth = tabs.getBoundingClientRect().width;
  const shortHeight = dialog.getBoundingClientRect().height;
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
  for (const name of ["Custom", "Automatic"]) {
    fireEvent.mouseDown(page.getByRole("tab", { name, exact: true }), {
      button: 0,
    });
    const heights = new Set<number>();
    const start = performance.now();
    while (performance.now() - start < 280) {
      await new Promise<void>((resolve) =>
        requestAnimationFrame(() => resolve())
      );
      heights.add(Math.round(dialog.getBoundingClientRect().height));
      expect(
        Math.abs(tabs.getBoundingClientRect().width - initialWidth)
      ).toBeLessThan(1);
      if (body.scrollHeight > body.clientHeight + 1) {
        expect(getComputedStyle(body).overflowY).toBe("hidden");
      }
    }
    if (reducedMotion) expect(heights.size).toBeLessThanOrEqual(2);
    else expect(heights.size).toBeGreaterThan(2);
  }
  expect(
    Math.abs(dialog.getBoundingClientRect().height - shortHeight)
  ).toBeLessThan(1);
  await userEvent.click(page.getByRole("button", { name: "Change spacing" }));
  await settleLayout();
  expect(dialog.getBoundingClientRect().height).toBeGreaterThan(
    shortHeight + 20
  );
  await userEvent.click(page.getByRole("button", { name: "Change spacing" }));
  await settleLayout();
  expect(
    Math.abs(dialog.getBoundingClientRect().height - shortHeight)
  ).toBeLessThan(1);
  for (const name of ["Long content", "Automatic", "Long content"]) {
    fireEvent.mouseDown(page.getByRole("tab", { name, exact: true }), {
      button: 0,
    });
    await new Promise<void>((resolve) =>
      requestAnimationFrame(() => resolve())
    );
  }
  await waitFor(() => expect(getComputedStyle(body).overflowY).toBe("auto"));
  expect(body.scrollHeight).toBeGreaterThan(body.clientHeight);
  body.scrollTop = body.scrollHeight;
  expect(body.scrollTop).toBeGreaterThan(0);
  const footer = page.getByRole("button", { name: "Done" });
  expect(footer.getBoundingClientRect().bottom).toBeLessThanOrEqual(
    innerHeight
  );
  await userEvent.click(footer);
  await userEvent.click(
    page.getByRole("button", { name: "Open animated modal" })
  );
  await expect(page.getByRole("tab", { name: "Long content" })).toHaveAttribute(
    "aria-selected",
    "true"
  );
  await userEvent.click(page.getByRole("button", { name: "Done" }));
}

export const AnimatedHeightRegression: Story = {
  render: () => <AnimatedHeightPreview />,
  play: verifyAnimatedHeight,
};

async function verifyConstrainedHeight() {
  const page = within(document.body);
  await userEvent.click(
    page.getByRole("button", { name: "Open animated modal" })
  );
  await userEvent.click(page.getByRole("tab", { name: "Long content" }));
  await settleLayout();
  const dialog = page.getByRole("dialog");
  const body = dialog.querySelector(".opal-modal-body");
  if (!(body instanceof HTMLElement)) throw new Error("Modal body missing");
  expect(getComputedStyle(body).overflowY).toBe("auto");
  expect(body.scrollHeight).toBeGreaterThan(body.clientHeight);
  body.scrollTop = body.scrollHeight;
  expect(body.scrollTop).toBeGreaterThan(0);
  expect(
    page.getByRole("button", { name: "Done" }).getBoundingClientRect().bottom
  ).toBeLessThanOrEqual(innerHeight - 16);
  expect(dialog.getBoundingClientRect().top).toBeGreaterThanOrEqual(0);
}

export const AnimatedHeightInitiallyLong: Story = {
  render: () => <AnimatedHeightPreview initialTab="long" />,
  play: verifyConstrainedHeight,
};

export const AnimatedHeightFixedCard: Story = {
  render: () => <AnimatedHeightPreview height="full" />,
  play: verifyConstrainedHeight,
};

export const AnimatedHeightWithBottomSlot: Story = {
  render: () => <AnimatedHeightPreview bottomSlot />,
  play: verifyConstrainedHeight,
};

export const AnimatedHeightTopPosition: Story = {
  render: () => <AnimatedHeightPreview position="top" initialTab="long" />,
  play: verifyConstrainedHeight,
};
