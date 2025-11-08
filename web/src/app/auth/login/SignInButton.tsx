import Button from "@/refresh-components/buttons/Button";
import { AuthType } from "@/lib/constants";
import Link from "next/link";
import { FcGoogle } from "react-icons/fc";
import { SvgProps } from "@/icons";

interface SignInButtonProps {
  authorizeUrl: string;
  authType: AuthType;
}

export default function SignInButton({
  authorizeUrl,
  authType,
}: SignInButtonProps) {
  let button: React.ReactNode;
  let icon: React.FunctionComponent<SvgProps> | undefined;

  if (authType === "google_oauth" || authType === "cloud") {
    button = "Continue with Google";
    icon = FcGoogle;
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
      <Button
        secondary={authType === "google_oauth" || authType === "cloud"}
        className="!w-full"
        leftIcon={icon}
      >
        {button}
      </Button>
    </Link>
  );
}
