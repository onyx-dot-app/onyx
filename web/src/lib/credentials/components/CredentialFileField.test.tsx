import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { Formik, type FormikProps } from "formik";
import { CredentialFileField } from "@/lib/credentials/components/CredentialFieldsRenderer";

jest.mock("@/lib/credentials/utils", () => {
  const actual = jest.requireActual("@/lib/credentials/utils");
  return { ...actual, fileToBase64: jest.fn(actual.fileToBase64) };
});

const utils = jest.requireMock("@/lib/credentials/utils");

interface CertificateForm {
  sp_private_key: string | null;
}

function renderField(onForm: (form: FormikProps<CertificateForm>) => void) {
  return render(
    <Formik<CertificateForm>
      initialValues={{ sp_private_key: null }}
      onSubmit={() => {}}
    >
      {(formik) => {
        onForm(formik);
        return (
          <CredentialFileField
            name="sp_private_key"
            fieldKey="sp_private_key"
            label="Private key"
            values="base64"
          />
        );
      }}
    </Formik>
  );
}

function picker(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector<HTMLInputElement>('input[type="file"]');
  if (!input) throw new Error("no file input");
  return input;
}

describe("CredentialFileField as base64", () => {
  it("holds the certificate's bytes as base64 text, and shows its name", async () => {
    const user = setupUser();
    let form: FormikProps<CertificateForm> | null = null;
    const { container } = render(
      <Formik<CertificateForm>
        initialValues={{ sp_private_key: null }}
        onSubmit={() => {}}
      >
        {(formik) => {
          form = formik;
          return (
            <CredentialFileField
              name="sp_private_key"
              fieldKey="sp_private_key"
              label="Private key"
              values="base64"
            />
          );
        }}
      </Formik>
    );
    const picker =
      container.querySelector<HTMLInputElement>('input[type="file"]');
    if (!picker) throw new Error("no file input");

    // Bytes that are not valid text, as a .pfx's are.
    await user.upload(
      picker,
      new File([new Uint8Array([0x30, 0x82, 0xff, 0x00, 0x01])], "app.pfx")
    );

    await waitFor(() => expect(form?.values.sp_private_key).toBe("MIL/AAE="));
    expect(screen.getByText("app.pfx")).toBeInTheDocument();
  });

  it("keeps the latest pick when an earlier read lands after it", async () => {
    const user = setupUser();
    const form: { current: FormikProps<CertificateForm> | null } = {
      current: null,
    };
    const { container } = renderField((formik) => (form.current = formik));
    let finishFirst: (value: string) => void = () => {};
    utils.fileToBase64
      .mockImplementationOnce(
        () => new Promise<string>((resolve) => (finishFirst = resolve))
      )
      .mockImplementationOnce(() => Promise.resolve("U0VDT05E"));

    await user.upload(picker(container), new File(["first"], "first.pfx"));
    await user.upload(picker(container), new File(["second"], "second.pfx"));
    await waitFor(() =>
      expect(form.current?.values.sp_private_key).toBe("U0VDT05E")
    );
    finishFirst("RklSU1Q=");

    await waitFor(() =>
      expect(screen.getByText("second.pfx")).toBeInTheDocument()
    );
    expect(form.current?.values.sp_private_key).toBe("U0VDT05E");
    expect(screen.queryByText("first.pfx")).not.toBeInTheDocument();
  });

  it("shows an error, and holds no file, when a read fails", async () => {
    const user = setupUser();
    const form: { current: FormikProps<CertificateForm> | null } = {
      current: null,
    };
    const { container } = renderField((formik) => (form.current = formik));
    utils.fileToBase64.mockImplementationOnce(() =>
      Promise.reject(new Error("unreadable"))
    );

    await user.upload(picker(container), new File(["x"], "broken.pfx"));

    expect(await screen.findByText("File selection error")).toBeInTheDocument();
    expect(form.current?.values.sp_private_key).toBeNull();
    expect(screen.queryByText("broken.pfx")).not.toBeInTheDocument();
  });
});
