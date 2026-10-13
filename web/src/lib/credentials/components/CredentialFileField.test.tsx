import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import { Formik, type FormikProps } from "formik";
import { CredentialFileField } from "@/lib/credentials/components/CredentialFieldsRenderer";

interface CertificateForm {
  sp_private_key: string | null;
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
});
