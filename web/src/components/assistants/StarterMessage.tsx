import { useContext } from "react";
import { MinimalPersonaSnapshot } from "../../app/admin/assistants/interfaces";
import { SettingsContext } from "../settings/SettingsProvider";

export function StarterMessages({
  currentPersona,
  onSubmit,
}: {
  currentPersona: MinimalPersonaSnapshot;
  onSubmit: (messageOverride: string) => void;
}) {
  const settings = useContext(SettingsContext);
  const isMobile = settings?.isMobile;
  return (
    <div
      key={-4}
      className={`
        short:hidden
        mx-auto
        w-full
        ${
          isMobile
            ? "gap-x-2 w-2/3 justify-between"
            : "justify-center max-w-[750px] items-start"
        }
        flex
      mt-6
      `}
    >
      {currentPersona?.starter_messages &&
        currentPersona.starter_messages.length > 0 && (
          <>
            {currentPersona.starter_messages
              .slice(0, isMobile ? 2 : 4)
              .map((starterMessage, i) => (
                <div
                  key={i}
                  className={`${
                    isMobile ? "w-1/2" : "w-1/4"
                  } flex justify-center`}
                >
                  <button
                    onClick={() => onSubmit(starterMessage.message)}
                    className={`
                      relative flex ${!isMobile ? "w-40" : "w-full max-w-52"}
                      shadow
                      border-background-300/60
                      flex-col gap-2 rounded-md
                      text-input-text hover:text-text
                      border
                      dark:bg-transparent
                      dark:border-neutral-700
                      dark:hover:bg-background-150
                      font-normal
                      px-3 py-2
                      text-start align-to text-wrap
                      text-[15px] shadow-xs transition
                      enabled:hover:bg-background-dark/75
                      disabled:cursor-not-allowed
                      overflow-hidden
                      break-words
                      truncate
                      text-ellipsis
                    `}
                    style={{ height: "5.6rem" }}
                  >
                    <div className="overflow-hidden text-ellipsis line-clamp-3 pr-1 pb-1">
                      {starterMessage.name}
                    </div>
                  </button>
                </div>
              ))}
          </>
        )}
    </div>
  );
}
