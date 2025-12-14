"use client";

import Button from "@/refresh-components/buttons/Button";
import { AuthType } from "@/lib/constants";
import { FcGoogle } from "react-icons/fc";
import { IconProps } from "@/icons";

interface SignInButtonProps {
  authorizeUrl: string;
  authType: AuthType;
}

export default function SignInButton({
  authorizeUrl,
  authType,
}: SignInButtonProps) {
  let button: React.ReactNode;
  let icon: React.FunctionComponent<IconProps> | undefined;

  if (authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD) {
    button = "Continue with Google";
    icon = FcGoogle;
  } else if (authType === AuthType.OIDC) {
    button = "Continue with OIDC SSO";
  } else if (authType === AuthType.SAML) {
    button = "Continue with SAML SSO";
  }

  const url = new URL(authorizeUrl);
  const finalAuthorizeUrl = url.toString();

  if (!button) {
    throw new Error(`Unhandled authType: ${authType}`);
  }

  return (
    <Button
      secondary={
        authType === AuthType.GOOGLE_OAUTH || authType === AuthType.CLOUD
      }
      className="!w-full"
      leftIcon={icon}
      href={finalAuthorizeUrl}
    >
      {button}
    </Button>
  );
}
