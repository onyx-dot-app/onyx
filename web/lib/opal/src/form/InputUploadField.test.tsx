import React from "react";
import { fireEvent, render, screen, waitFor } from "@tests/setup/test-utils";
import "@testing-library/jest-dom";
import userEvent from "@testing-library/user-event";
import { Formik, type FormikProps } from "formik";
import { InputUploadField } from "@opal/form/InputUploadField";

interface KeyForm {
  key: string;
}

interface CertificateForm {
  certificate: File | null;
}

function picker(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  return input;
}

describe("InputUploadField", () => {
  test("text mode: a paste into the focused control becomes the value", async () => {
    const user = userEvent.setup({ delay: null });
    let form: FormikProps<KeyForm> | null = null;
    render(
      <Formik<KeyForm> initialValues={{ key: "" }} onSubmit={() => {}}>
        {(formik) => {
          form = formik;
          return <InputUploadField name="key" placeholder="Upload a key" />;
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
          return <InputUploadField name="key" />;
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
          return <InputUploadField name="key" placeholder="Upload a key" />;
        }}
      </Formik>
    );
    const trigger = screen.getByRole("button", { name: "Upload a key" });

    // The picker takes focus; the field is still being filled in.
    await user.click(trigger);
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
          return <InputUploadField name="key" />;
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
          return <InputUploadField name="key" />;
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
          return <InputUploadField name="key" />;
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
          return <InputUploadField name="certificate" mode="file" />;
        }}
      </Formik>
    );

    await user.upload(picker(container), certificate);

    await waitFor(() => expect(form?.values.certificate).toBe(certificate));
    expect(screen.getByText("app.pfx")).toBeInTheDocument();
  });

  test("a touched field with an error shows the error variant", () => {
    const { container } = render(
      <Formik<KeyForm>
        initialValues={{ key: "" }}
        initialTouched={{ key: true }}
        initialErrors={{ key: "Required" }}
        onSubmit={() => {}}
      >
        <InputUploadField name="key" />
      </Formik>
    );

    expect(container.querySelector(".opal-input")).toHaveAttribute(
      "data-variant",
      "error"
    );
  });
});
