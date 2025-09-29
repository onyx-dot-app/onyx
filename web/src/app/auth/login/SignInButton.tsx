import i18n from "@/i18n/init-server";
import k from "@/i18n/keys";
import { AuthType } from "@/lib/constants";
import { FaGoogle } from "react-icons/fa";

export function SignInButton({
  authorizeUrl,
  authType,
}: {
  authorizeUrl: string;
  authType: AuthType;
}) {
  let button;
  if (authType === "google_oauth" || authType === "cloud") {
    button = (
      <div className="mx-auto flex">
        <div className="my-auto mr-2">
          <FaGoogle />
        </div>
        <p className="text-sm font-medium select-none">
          {i18n.t(k.CONTINUE_WITH_GOOGLE)}
        </p>
      </div>
    );
  } else if (authType === "oidc") {
    button = (
      <div className="mx-auto flex">
        <p className="text-sm font-medium select-none">
          {i18n.t(k.CONTINUE_WITH_OIDC_SSO)}
        </p>
      </div>
    );
  } else if (authType === "saml") {
    button = (
      <div className="mx-auto flex">
        <p className="text-sm font-medium select-none">
          {i18n.t(k.CONTINUE_WITH_SAML_SSO)}
        </p>
      </div>
    );
  }

  const url = new URL(authorizeUrl);

  const finalAuthorizeUrl = url.toString();

  if (!button) {
    throw new Error(`Unhandled authType: ${authType}`);
  }

  return (
    <a
      className="mx-auto mb-4 mt-6 py-3 w-full dark:text-neutral-300 text-neutral-600 border border-neutral-300 flex rounded cursor-pointer hover:border-neutral-400 transition-colors"
      href={finalAuthorizeUrl}
    >
      {button}
    </a>
  );
}
