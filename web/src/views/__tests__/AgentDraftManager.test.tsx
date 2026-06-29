import React from "react";
import { render, screen, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Formik, useFormikContext } from "formik";
import { AgentDraftManager } from "@/views/AgentEditorPage";
import { draftKey } from "@/hooks/useDraft";

const KEY = draftKey("agent-editor", "new");

// Surfaces the live form value and lets a test dirty the form.
function FormReadout() {
  const { values, setFieldValue } = useFormikContext<{ name: string }>();
  return (
    <>
      <div data-testid="name">{values.name}</div>
      <button onClick={() => setFieldValue("name", "edited")}>edit</button>
    </>
  );
}

function renderManager() {
  const clearRef = React.createRef<(() => void) | null>();
  const utils = render(
    <Formik
      initialValues={{ name: "" }}
      onSubmit={() => {}}
      validateOnChange={false}
      validateOnBlur={false}
      validateOnMount={false}
    >
      <>
        <AgentDraftManager storageKey={KEY} clearRef={clearRef} />
        <FormReadout />
      </>
    </Formik>
  );
  return { ...utils, clearRef };
}

describe("AgentDraftManager", () => {
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

  it("auto-restores a stored draft into the form on mount", () => {
    sessionStorage.setItem(KEY, JSON.stringify({ name: "draft name" }));
    renderManager();
    expect(screen.getByTestId("name")).toHaveTextContent("draft name");
  });

  it("leaves the form untouched when there is no stored draft", () => {
    renderManager();
    expect(screen.getByTestId("name").textContent).toBe("");
  });

  // The save-success path calls clearRef (the hook's clear()), which must
  // cancel a debounced write scheduled by the edit. A bare removeItem would let
  // the pending timer rewrite the key right after, resurrecting the saved
  // values.
  it("clearRef cancels a pending debounced write before removing the draft", () => {
    const { clearRef } = renderManager();

    // Editing schedules a debounced save(values).
    fireEvent.click(screen.getByText("edit"));

    // Save succeeds before the debounce fires; the parent clears via the ref.
    act(() => {
      clearRef.current?.();
    });
    act(() => {
      jest.advanceTimersByTime(300);
    });

    // The cancelled timer must not have rewritten the key.
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });
});
