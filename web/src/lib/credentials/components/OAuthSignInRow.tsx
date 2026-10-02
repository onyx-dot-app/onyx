"use client";

import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { InputHorizontal } from "@opal/layouts";
import { SvgArrowExchange } from "@opal/icons";

interface OAuthSignInRowProps {
  /** The source's display name, e.g. "Confluence". */
  source: string;
  /** Leaves for the provider. Omit when the button submits its form. */
  onConnect?: () => void;
  disabled?: boolean;
}

/**
 * The OAuth route's action row: "Sign in with {source}" on the left, the
 * Connect button on the right. Inside a form, the button submits it.
 */
export function OAuthSignInRow({
  source,
  onConnect,
  disabled,
}: OAuthSignInRowProps) {
  const t = useTranslations("admin.credentials.oauth");
  return (
    <InputHorizontal title={t("signIn.title", { source })} center>
      <Button
        icon={SvgArrowExchange}
        disabled={disabled}
        type={onConnect ? "button" : "submit"}
        onClick={onConnect}
      >
        {t("connectButton.label")}
      </Button>
    </InputHorizontal>
  );
}
