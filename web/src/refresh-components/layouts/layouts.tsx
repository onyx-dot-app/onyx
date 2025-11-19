import { ChatSession } from "@/app/chat/interfaces";
import { cn } from "@/lib/utils";
import Text from "@/refresh-components/texts/Text";
import Button from "../buttons/Button";
import SvgShare from "@/icons/share";
import { CombinedSettings } from "@/app/admin/settings/interfaces";
import { useState } from "react";

interface AppPageProps extends React.HtmlHTMLAttributes<HTMLDivElement> {
  settings: CombinedSettings | null;
  chatSession: ChatSession | null;
}

async function AppPage({
  settings,
  chatSession,
  className,
  ...rest
}: AppPageProps) {
  const [showShareModal, setShowShareModal] = useState(false);

  const customHeaderContent =
    settings?.enterpriseSettings?.custom_header_content;

  return (
    <div className="flex flex-col h-full w-full">
      {(customHeaderContent || chatSession) && (
        <header className="w-full flex flex-row justify-center items-center py-3 px-4 h-16 dbg-red">
          <div className="flex-1" />
          <div className="flex-1 flex flex-col items-center">
            <Text text03>{customHeaderContent}</Text>
          </div>
          <div className="flex-1 flex flex-row items-center justify-end px-1">
            <Button
              leftIcon={SvgShare}
              transient={showShareModal}
              tertiary
              onClick={() => setShowShareModal(true)}
              className={cn(!chatSession && "invisible")}
            />
          </div>
        </header>
      )}

      <div className={cn("flex-1 overflow-auto", className)} {...rest} />
    </div>
  );
}

export { AppPage };
