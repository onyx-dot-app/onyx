import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { AuthType } from "@/lib/constants";
import Link from "next/link";
import { FaGoogle } from "react-icons/fa";
import { SiAuth0 } from "react-icons/si";

interface SignInButtonProps {
  authorizeUrl: string;
  authType: AuthType;
}

export default function SignInButton({
  authorizeUrl,
  authType,
}: SignInButtonProps) {
  let button: React.ReactNode;

  if (authType === "google_oauth" || authType === "cloud") {
    button = (
      <div className="flex flex-row items-center justify-center w-full gap-spacing-interline">
        <FaGoogle className="text-text-inverted-04" />
        <Text inverted>Continue with Google</Text>
      </div>
    );
  } else if (authType === "auth0") {
    button = (
      <div className="mx-auto flex">
        <div className="my-auto mr-2">
          <SiAuth0 />
        </div>
        <p className="text-sm font-medium select-none">Continue with Auth0</p>
      </div>
    );

  } else if (authType === "oidc") {
    button = "Continue with OIDC SSO";
  } else if (authType === "saml") {
    button = "Continue with SAML SSO";
  }

  const url = new URL(authorizeUrl);
  const finalAuthorizeUrl = url.toString();

  if (!button) {
    throw new Error(`Unhandled authType: ${authType}`);
  }

  return (
    <Link href={finalAuthorizeUrl}>
      <Button className="!w-full">{button}</Button>
    </Link>
  );
}
