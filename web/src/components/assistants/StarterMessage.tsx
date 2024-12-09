import { useContext } from "react";
import { Persona } from "../../app/admin/assistants/interfaces";
import { SettingsContext } from "../settings/SettingsProvider";

export function StarterMessages({
  currentPersona,
  onSubmit,
}: {
  currentPersona: Persona;
  onSubmit: (messageOverride: string) => void;
}) {
  const settings = useContext(SettingsContext);
  const isMobile = settings?.isMobile;
  return (
    <div
      key={-4}
      className={`
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
                <div key={i} className={`${isMobile ? "w-1/2" : "w-1/4"}`}>
                  <button
                    onClick={() => onSubmit(starterMessage.message)}
                    className={`relative flex ${
                      !isMobile && "w-40"
                    } flex-col gap-2 rounded-2xl shadow-sm border border-border bg-background-starter-message px-3 py-2 text-start align-to text-wrap text-[15px] shadow-xs transition enabled:hover:bg-background-starter-message-hover disabled:cursor-not-allowed line-clamp-3`}
                    style={{ height: `5.2rem` }}
                  >
                    {starterMessage.name}
                  </button>
                </div>
              ))}
          </>
        )}
    </div>
  );
}
