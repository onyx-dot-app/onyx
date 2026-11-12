/**
 * @jest-environment jsdom
 */
import { act, render, screen } from "@tests/setup/test-utils";
import { Button } from "@opal/components";
import { ToastProvider, toast } from "@opal/layouts";
import { useSkillsLeftOffToast } from "@/sections/skills/SkillOmissionList";
import type { SkillLimitNotice } from "@/lib/skills/limits";

const MB = 1024 * 1024;

function Harness({ notice }: { notice: SkillLimitNotice | null }) {
  const show = useSkillsLeftOffToast();
  return <Button onClick={() => show(notice)}>{"connect"}</Button>;
}

describe("useSkillsLeftOffToast", () => {
  afterEach(() => toast.clearAll());

  it("lists the app skills left off and why", () => {
    render(
      <ToastProvider>
        <Harness
          notice={{
            max_bytes: 500 * MB,
            max_files: 5000,
            skills: [
              {
                plugin_id: "p1",
                name: "slack-digest",
                bytes: 30 * MB,
                files: 4,
                reason: "bytes",
              },
            ],
          }}
        />
      </ToastProvider>
    );

    act(() => screen.getByRole("button", { name: "connect" }).click());

    expect(screen.getByText("1 skill stayed off")).toBeInTheDocument();
    expect(
      screen.getByText(/would put you past the 500 MB skill limit/)
    ).toBeInTheDocument();
    expect(screen.getByText("slack-digest: 30 MB")).toBeInTheDocument();
  });

  it("shows nothing when no skill was left off", () => {
    render(
      <ToastProvider>
        <Harness notice={null} />
      </ToastProvider>
    );

    act(() => screen.getByRole("button", { name: "connect" }).click());

    expect(screen.queryByText(/stayed off/)).not.toBeInTheDocument();
  });
});
