import { render, screen, setupUser } from "@tests/setup/test-utils";
import { FetchError } from "@/lib/fetcher";
import { useSkillErrorToast, useSkillLimitFeedback } from "@/lib/skills/hooks";
import { toast, ToastProvider } from "@opal/layouts";
import type { SkillUsageSummary } from "@/lib/skills/limits";

const MiB = 1024 * 1024;

function usage(overrides: Partial<SkillUsageSummary> = {}): SkillUsageSummary {
  return {
    bytes: 520 * MiB,
    files: 40,
    unknown_skill_count: 0,
    charged_bytes: 520 * MiB,
    charged_files: 40,
    max_bytes: 500 * MiB,
    max_files: 5000,
    ...overrides,
  };
}

function refusal(skillLimit: unknown, status = 413) {
  return new FetchError("Server detail", status, {
    error_code: "PAYLOAD_TOO_LARGE",
    detail: "Server detail",
    skill_limit: skillLimit,
  });
}

function Feedback({ error }: { error: unknown }) {
  const feedback = useSkillLimitFeedback()(error);
  return feedback ? (
    <>
      <p>{feedback.title}</p>
      <p>{feedback.description}</p>
    </>
  ) : (
    <p>ordinary</p>
  );
}

describe("useSkillLimitFeedback", () => {
  it("shows the requester's measured usage and the limits", () => {
    render(
      <Feedback
        error={refusal({
          failed_limit: "bytes",
          affected_user_count: 1,
          usage: usage(),
        })}
      />
    );
    expect(screen.getByText("Skill size limit reached")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This change would put your skills at 520 MiB in 40 files. The limit is 500 MiB and 5,000 files."
      )
    ).toBeInTheDocument();
  });

  it("labels charged totals as an estimate when Skills are unmeasured", () => {
    render(
      <Feedback
        error={refusal({
          failed_limit: "files",
          affected_user_count: 3,
          usage: usage({
            bytes: 10 * MiB,
            files: 4,
            unknown_skill_count: 1,
            charged_bytes: 110 * MiB,
            charged_files: 5004,
          }),
        })}
      />
    );
    expect(screen.getByText("Skill file limit reached")).toBeInTheDocument();
    expect(
      screen.getByText(
        "This change would put your skills at an estimated 110 MiB in 5,004 files. The estimate counts 1 skill not yet measured at the largest allowed size. The limit is 500 MiB and 5,000 files. It would also put 2 other users over the limit."
      )
    ).toBeInTheDocument();
    expect(screen.queryByText(/\b10 MiB/)).not.toBeInTheDocument();
  });

  it("shows the affected-user count when the requester stays within the limit", () => {
    render(
      <Feedback
        error={refusal({
          failed_limit: "bytes",
          affected_user_count: 4,
          usage: null,
        })}
      />
    );
    expect(
      screen.getByText(
        "This change would put 4 users over the skill size limit."
      )
    ).toBeInTheDocument();
  });

  it("leaves plain payload errors and other failures to the caller", () => {
    const { rerender } = render(<Feedback error={refusal(undefined)} />);
    expect(screen.getByText("ordinary")).toBeInTheDocument();
    rerender(<Feedback error={new Error("Network down")} />);
    expect(screen.getByText("ordinary")).toBeInTheDocument();
  });
});

it("replaces repeated limit refusals with the latest explanation", async () => {
  function RefusalButtons() {
    const showError = useSkillErrorToast();
    return (
      <>
        {(["bytes", "files"] as const).map((limit) => (
          <button
            key={limit}
            onClick={() =>
              showError(
                refusal({
                  failed_limit: limit,
                  affected_user_count: 1,
                  usage: usage(),
                }),
                "Failed"
              )
            }
          >
            {limit}
          </button>
        ))}
      </>
    );
  }
  toast.clearAll();
  try {
    const user = setupUser();
    render(
      <ToastProvider>
        <RefusalButtons />
      </ToastProvider>
    );
    await user.click(screen.getByRole("button", { name: "bytes" }));
    expect(screen.getByText("Skill size limit reached")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "files" }));
    expect(screen.getByText("Skill file limit reached")).toBeInTheDocument();
    expect(
      screen.queryByText("Skill size limit reached")
    ).not.toBeInTheDocument();
  } finally {
    toast.clearAll();
  }
});

it("uses the fallback when an ordinary error has no message", async () => {
  function ErrorButton() {
    const showError = useSkillErrorToast();
    return (
      <button onClick={() => showError(new Error(""), "Save failed")}>
        Save
      </button>
    );
  }
  toast.clearAll();
  try {
    const user = setupUser();
    render(
      <ToastProvider>
        <ErrorButton />
      </ToastProvider>
    );
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(screen.getByText("Save failed")).toBeInTheDocument();
  } finally {
    toast.clearAll();
  }
});
