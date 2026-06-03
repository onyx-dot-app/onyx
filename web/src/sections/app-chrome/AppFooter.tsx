"use client";

import { cn } from "@opal/utils";
import { ensureHrefProtocol } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import type { Components } from "react-markdown";
import MinimalMarkdown from "@/components/chat/MinimalMarkdown";
import { useSettingsContext } from "@/providers/SettingsProvider";
import useAppFocus from "@/hooks/useAppFocus";
import { APP_SLOGAN } from "@/lib/constants";

const footerMarkdownComponents = {
  p: ({ children }) => (
    <Text as="p" text03 secondaryAction className="my-0! text-center">
      {children}
    </Text>
  ),
  a: ({ node, href, className, children, ...rest }) => {
    const fullHref = ensureHrefProtocol(href);
    return (
      <a
        href={fullHref}
        target="_blank"
        rel="noopener noreferrer"
        {...rest}
        className={cn(className, "underline underline-offset-2")}
      >
        <Text text03 secondaryAction>
          {children}
        </Text>
      </a>
    );
  },
} satisfies Partial<Components>;

export default function AppFooter() {
  const settings = useSettingsContext();
  const appFocus = useAppFocus();

  const customFooterContent =
    settings?.enterpriseSettings?.custom_lower_disclaimer_content ||
    `[Onyx ${
      settings?.webVersion || "dev"
    }](https://www.onyx.app/) - ${APP_SLOGAN}`;

  return (
    <footer
      className={cn(
        "relative w-full flex flex-row justify-center items-center gap-2 px-2 mt-auto",
        // # Note (from @raunakab):
        //
        // The conditional rendering of vertical padding based on the current page is intentional.
        // The `AppInputBar` has `shadow-01` applied, which extends ~14px below it.
        // Because the content area in `AppChrome` uses `overflow-auto`, the shadow would be
        // clipped at the container boundary — causing a visible rendering artefact.
        //
        // To fix this, `AppPage.tsx` uses animated spacer divs around `AppInputBar` to
        // give the shadow breathing room. However, that extra space adds visible gap
        // between the input and the Footer. To compensate, we remove the Footer's top
        // padding when `appFocus.isChat()`.
        //
        // There is a corresponding note inside `AppInputBar.tsx` and `AppPage.tsx`
        // explaining this. Please refer to those notes as well.
        appFocus.isChat() ? "pb-2" : "py-2"
      )}
    >
      <MinimalMarkdown
        content={customFooterContent}
        className={cn("max-w-full text-center")}
        components={footerMarkdownComponents}
      />
    </footer>
  );
}
