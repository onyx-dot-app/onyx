import { useAutoAnimate } from "@formkit/auto-animate/react";
import { DeepAction, DeepActionType } from "./deepResearchAction";
type DeepActionRenderer<T extends DeepAction> = ({
  action,
}: {
  action: T;
}) => JSX.Element;

export const RunCommandAction: DeepActionRenderer<
  DeepActionType<"run_command">
> = ({ action }) => {
  return <div>{action.cmd}</div>;
};

export const DeepThinkingAction: DeepActionRenderer<
  DeepActionType<"thinking">
> = ({ action }) => {
  return <div className="opacity-60">{action.thinking}...</div>;
};

export const WebSearchAction: DeepActionRenderer<
  DeepActionType<"web_search">
> = ({ action }) => {
  const [parent] = useAutoAnimate();
  return (
    <div className="space-y-2">
      <div className="text-sm text-neutral-400">
        Searching the web for: {action.query}
      </div>
      <div ref={parent} className="flex items-start gap-2 overflow-x-auto pb-2">
        {action.results.map((result) => (
          <a
            key={result.url}
            href={result.url}
            target="_blank"
            rel="noreferrer"
            className="flex-shrink-0 w-48 p-3 rounded-lg border border-neutral-500 hover:border-gray-300 transition-colors"
          >
            <div className="flex items-center gap-2 mb-1">
              <img
                src={`https://www.google.com/s2/favicons?domain=${
                  new URL(result.url).hostname
                }`}
                alt=""
                className="w-4 h-4"
              />
              <div className="text-sm line-clamp-1 overflow-ellipsis font-medium">
                {result.title}
              </div>
            </div>
          </a>
        ))}
      </div>
    </div>
  );
};
