import React from "react";
import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { Formik, type FormikProps } from "formik";
import { InputSingleUploadField } from "@opal/form/InputSingleUploadField";
import { InputMultiUploadField } from "@opal/form/InputMultiUploadField";

interface KeyForm {
  key: string;
}

interface CertificateForm {
  certificate: File | null;
}

interface FilesForm {
  files: File[];
}

/** Focuses `target` and pastes `files`, as a click then Cmd+V does. */
function pasteFiles(target: HTMLElement, files: File[]): void {
  target.focus();
  fireEvent.paste(target, {
    clipboardData: {
      types: ["Files"],
      items: files.map((file) => ({ kind: "file", getAsFile: () => file })),
      files,
      getData: () => "",
    },
  });
}

function picker(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  return input;
}

describe("InputSingleUploadField", () => {
  test("text mode: a paste into the focused control becomes the value", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return (
            <InputSingleUploadField name="key" placeholder="Upload a key" />
          );
        }}
      </Formik>
    );

    await user.click(screen.getByRole("button", { name: "Upload a key" }));
    await user.paste("eyJsaWNlbnNl");

    await waitFor(() => expect(form?.values.key).toBe("eyJsaWNlbnNl"));
    expect(screen.getByText("Pasted text")).toBeInTheDocument();
  });

  test("Delete clears an upload from the keyboard, and the × returns focus", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    const { container } = render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return <InputSingleUploadField name="key" />;
        }}
      </Formik>
    );
    const trigger = container.querySelector<HTMLButtonElement>(
      ".opal-input-upload-trigger"
    );
    if (!trigger) throw new Error("no trigger");

    await user.upload(picker(container), new File(["one"], "one.txt"));
    await waitFor(() => expect(form?.values.key).toBe("one"));
    trigger.focus();
    await user.keyboard("{Delete}");
    await waitFor(() => expect(form?.values.key).toBe(""));

    await user.upload(picker(container), new File(["two"], "two.txt"));
    await waitFor(() => expect(form?.values.key).toBe("two"));
    await user.click(screen.getByRole("button", { name: "Clear file" }));
    await waitFor(() => expect(form?.values.key).toBe(""));
    expect(trigger).toHaveFocus();
  });

  test("opening the picker does not mark the field touched", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    const { container } = render(
      <Formik<KeyForm>
        initialValues={{ key: "" }}
        validate={(values) => (values.key ? {} : { key: "Required" })}
        onSubmit={() => {}}
      >
        {(formik) => {
          form = formik;
          return (
            <InputSingleUploadField name="key" placeholder="Upload a key" />
          );
        }}
      </Formik>
    );
    const trigger = screen.getByRole("button", { name: "Upload a key" });

    // A double click opens the picker, which takes focus; the field is still
    // being filled in.
    await user.dblClick(trigger);
    fireEvent.blur(trigger);
    expect(form?.touched.key).toBeFalsy();
    expect(container.querySelector(".opal-input")).toHaveAttribute(
      "data-variant",
      "primary"
    );

    // Cancelled, focus returns; leaving the field then counts.
    fireEvent(picker(container), new Event("cancel"));
    expect(trigger).toHaveFocus();
    fireEvent.blur(trigger);
    await waitFor(() => expect(form?.touched.key).toBe(true));
  });

  test("the × clears an upload", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    const { container } = render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return <InputSingleUploadField name="key" />;
        }}
      </Formik>
    );

    await user.upload(picker(container), new File(["secret"], "key.txt"));
    await waitFor(() => expect(form?.values.key).toBe("secret"));
    await user.click(screen.getByRole("button", { name: "Clear file" }));

    await waitFor(() => expect(form?.values.key).toBe(""));
    expect(screen.queryByText("key.txt")).not.toBeInTheDocument();
  });

  test("text mode: an attached file's text becomes the value, and its name shows", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    const { container } = render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return <InputSingleUploadField name="key" />;
        }}
      </Formik>
    );

    await user.upload(
      picker(container),
      new File(['{"a":1}'], "key.json", { type: "application/json" })
    );

    await waitFor(() => expect(form?.values.key).toBe('{"a":1}'));
    expect(screen.getByText("key.json")).toBeInTheDocument();
    expect(form?.touched.key).toBe(true);
  });

  test("text mode: a form reset clears the field", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    const { container } = render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return <InputSingleUploadField name="key" />;
        }}
      </Formik>
    );

    await user.upload(picker(container), new File(["secret"], "key.txt"));
    await waitFor(() => expect(form?.values.key).toBe("secret"));
    form?.resetForm();

    await waitFor(() =>
      expect(screen.queryByText("key.txt")).not.toBeInTheDocument()
    );
  });

  test("file mode: the field holds the File itself", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<CertificateForm> | null = null;
    const certificate = new File([new Uint8Array([0, 255, 1])], "app.pfx");
    const { container } = render(
      <Formik<CertificateForm>
        initialValues={{ certificate: null }}
        onSubmit={() => {}}
      >
        {(formik) => {
          form = formik;
          return <InputSingleUploadField name="certificate" mode="file" />;
        }}
      </Formik>
    );

    await user.upload(picker(container), certificate);

    await waitFor(() => expect(form?.values.certificate).toBe(certificate));
    expect(screen.getByText("app.pfx")).toBeInTheDocument();
  });

  test("Enter and Space open the picker; a click only focuses", async () => {
    const user = userEvent.setup({ delay: null });
    const { container } = render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {() => <InputSingleUploadField name="key" placeholder="Upload a key" />}
      </Formik>
    );
    const trigger = screen.getByRole("button", { name: "Upload a key" });
    const open = jest.spyOn(picker(container), "click");

    await user.click(trigger);
    expect(trigger).toHaveFocus();
    expect(open).not.toHaveBeenCalled();

    await user.keyboard("{Enter}");
    await user.keyboard(" ");
    expect(open).toHaveBeenCalledTimes(2);
  });

  test("file mode: a pasted file replaces the value", async () => {
    let form: FormikProps<CertificateForm> | null = null;
    render(
      <Formik<CertificateForm>
        initialValues={{ certificate: null }}
        onSubmit={() => {}}
      >
        {(formik) => {
          form = formik;
          return (
            <InputSingleUploadField
              name="certificate"
              mode="file"
              placeholder="Upload a certificate"
            />
          );
        }}
      </Formik>
    );
    const trigger = screen.getByRole("button", {
      name: "Upload a certificate",
    });
    const first = new File(["one"], "one.pfx");
    const second = new File(["two"], "two.pfx");

    pasteFiles(trigger, [first]);
    await waitFor(() => expect(form?.values.certificate).toBe(first));
    pasteFiles(trigger, [second]);
    await waitFor(() => expect(form?.values.certificate).toBe(second));
  });

  test("a pasted file outside `accept` or the size limit is rejected", async () => {
    let form: FormikProps<CertificateForm> | null = null;
    const onFileSizeExceeded = jest.fn();
    render(
      <Formik<CertificateForm>
        initialValues={{ certificate: null }}
        onSubmit={() => {}}
      >
        {(formik) => {
          form = formik;
          return (
            <InputSingleUploadField
              name="certificate"
              mode="file"
              placeholder="Upload a certificate"
              accept=".pfx"
              maxSizeKb={1}
              onFileSizeExceeded={onFileSizeExceeded}
            />
          );
        }}
      </Formik>
    );
    const trigger = screen.getByRole("button", {
      name: "Upload a certificate",
    });

    pasteFiles(trigger, [new File(["x"], "notes.txt")]);
    pasteFiles(trigger, [new File(["x".repeat(2048)], "big.pfx")]);

    // A paste is read asynchronously, as a drop is.
    await waitFor(() => expect(onFileSizeExceeded).toHaveBeenCalledTimes(1));
    expect(form?.values.certificate).toBeNull();
  });

  test("a touched field with an error shows the error variant", () => {
    const { container } = render(
      <Formik<KeyForm>
        initialValues={{ key: "" }}
        initialTouched={{ key: true }}
        initialErrors={{ key: "Required" }}
        onSubmit={() => {}}
      >
        <InputSingleUploadField name="key" />
      </Formik>
    );

    expect(container.querySelector(".opal-input")).toHaveAttribute(
      "data-variant",
      "error"
    );
  });
});

describe("InputMultiUploadField", () => {
  test("pasted files are added, without repeats", async () => {
    let form: FormikProps<FilesForm> | null = null;
    const { container } = render(
      <Formik<FilesForm> initialValues={{ files: [] }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return <InputMultiUploadField name="files" />;
        }}
      </Formik>
    );
    const trigger = container.querySelector<HTMLElement>(
      ".opal-input-type-in-tag-trigger"
    );
    if (!trigger) throw new Error("no trigger");
    const one = new File(["one"], "one.txt");
    const two = new File(["two"], "two.txt");

    pasteFiles(trigger, [one, two]);
    await waitFor(() => expect(form?.values.files).toEqual([one, two]));
    pasteFiles(trigger, [two]);
    await waitFor(() => expect(form?.values.files).toEqual([one, two]));
  });
});

describe("upload paste", () => {
  test("a paste goes to the focused upload, wherever the event lands", async () => {
    let form: FormikProps<FilesForm & CertificateForm> | null = null;
    render(
      <Formik<FilesForm & CertificateForm>
        initialValues={{ certificate: null, files: [] }}
        onSubmit={() => {}}
      >
        {(formik) => {
          form = formik;
          return (
            <>
              <InputSingleUploadField
                name="certificate"
                mode="file"
                placeholder="Upload a certificate"
              />
              <InputMultiUploadField name="files" />
            </>
          );
        }}
      </Formik>
    );
    const trigger = screen.getByRole("button", {
      name: "Upload a certificate",
    });
    const file = new File(["one"], "one.pfx");
    trigger.focus();

    // Browsers send the event to the text selection, here the page body.
    fireEvent.paste(document.body, {
      clipboardData: {
        types: ["Files"],
        items: [{ kind: "file", getAsFile: () => file }],
        files: [file],
        getData: () => "",
      },
    });

    await waitFor(() => expect(form?.values.certificate).toBe(file));
    expect(form?.values.files).toEqual([]);
  });
});
