import React from "react";
import { render, screen, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Formik, useFormikContext } from "formik";
import { AgentDraftManager } from "@/views/AgentEditorPage";
import { draftKey } from "@/hooks/useDraft";

const KEY = draftKey("agent-editor", "test");
const BANNER = "Restore unsaved changes?";

// Drives Formik dirtiness from the test: "edit" makes the form dirty, "revert"
// returns it to initialValues (pristine).
function FormControls() {
  const { setFieldValue } = useFormikContext<{ name: string }>();
  return (
    <>
      <button onClick={() => setFieldValue("name", "edited")}>edit</button>
      <button onClick={() => setFieldValue("name", "")}>revert</button>
    </>
  );
}

function renderManager() {
  return render(
    <Formik
      initialValues={{ name: "" }}
      onSubmit={() => {}}
      validateOnChange={false}
      validateOnBlur={false}
      validateOnMount={false}
    >
      <>
        <AgentDraftManager storageKey={KEY} />
        <FormControls />
      </>
    </Formik>
  );
}

describe("AgentDraftManager banner", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    sessionStorage.clear();
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it("shows the restore banner for a pristine form with a stored draft", () => {
    sessionStorage.setItem(KEY, JSON.stringify({ name: "draft name" }));
    renderManager();
    expect(screen.getByText(BANNER)).toBeInTheDocument();
  });

  it("does not show the banner when there is no stored draft", () => {
    renderManager();
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
  });

  it("hides the banner once the form becomes dirty", () => {
    sessionStorage.setItem(KEY, JSON.stringify({ name: "draft name" }));
    renderManager();
    expect(screen.getByText(BANNER)).toBeInTheDocument();

    fireEvent.click(screen.getByText("edit"));

    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
  });

  it("keeps the banner hidden after the form is reverted to pristine (latch)", () => {
    sessionStorage.setItem(KEY, JSON.stringify({ name: "draft name" }));
    renderManager();

    fireEvent.click(screen.getByText("edit"));
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();

    // Reverting back to initialValues makes Formik pristine again; the latch
    // must keep the banner from reappearing.
    fireEvent.click(screen.getByText("revert"));
    expect(screen.queryByText(BANNER)).not.toBeInTheDocument();
  });
});
