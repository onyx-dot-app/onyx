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
        <p className="text-sm font-medium select-none">Continue with Google</p>
      </div>
    );
  } else if (authType === "oidc") {
    button = (
      <div className="mx-auto flex">
        <p className="text-sm font-medium select-none">
          Continue with OIDC SSO
        </p>
      </div>
    );
  } else if (authType === "saml") {
    button = (
      <div className="mx-auto flex">
        <p className="text-sm font-medium select-none">
          Continue with SAML SSO
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
      className="mx-auto mt-6 py-3 w-full text-text-100 bg-accent flex rounded cursor-pointer hover:bg-indigo-800"
      href={finalAuthorizeUrl}
    >
      {button}
    </a>
  );
}
