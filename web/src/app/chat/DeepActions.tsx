import { useAutoAnimate } from "@formkit/auto-animate/react";
import {
  CollapsibleDeepAction,
  DeepAction,
  DeepActionType,
} from "./deepResearchAction";
import { Terminal, Spinner, Check } from "@phosphor-icons/react";
type DeepActionRenderer<T extends DeepAction> = ({
  action,
}: // onCollapse,
{
  action: T;
  // onCollapse?: T extends CollapsibleDeepAction ? (collapsed: boolean) => void : undefined;
}) => JSX.Element;

export const RunCommandAction: DeepActionRenderer<
  DeepActionType<"run_command">
> = ({ action }) => {
  return (
    <div>
      <div className="flex items-center opacity-70 gap-2">
        <Terminal size={18} />
        <div className="font-mono text-xs">{action.cmd}</div>
      </div>
      {!action.collapsed && (
        <div className="max-h-[100px] bg-neutral-800 p-1 rounded text-sm opacity-70 overflow-y-scroll font-mono">
          {action.result}
        </div>
      )}
    </div>
  );
};

export const DeepThinkingAction: DeepActionRenderer<
  DeepActionType<"thinking">
> = ({ action }) => {
  return <div className="opacity-60">{action.thinking}...</div>;
};

export const DeepSendEmail: DeepActionRenderer<DeepActionType<"email">> = ({
  action,
}) => {
  return <div className="opacity-60">Sending email to: {action.email}...</div>;
};

export const DeepProcessAction: DeepActionRenderer<
  DeepActionType<"process">
> = ({ action }) => {
  return (
    <div className="flex items-center gap-2 opacity-70">
      {action.done ? (
        <Check size={18} weight="bold" className="text-green-500" />
      ) : (
        <Spinner size={18} className="animate-spin" />
      )}
      <div className="text-sm">{action.description}</div>
    </div>
  );
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
      {!action.collapsed && (
        <div
          ref={parent}
          className="flex items-start gap-2 overflow-x-auto pb-2"
        >
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
      )}
    </div>
  );
};
