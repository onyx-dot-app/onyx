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
  return (
    <div className="">
      <div>Searching the web for: {action.query}</div>
      {action.results.map((result) => (
        <div key={result.url}>
          <a href={result.url} target="_blank" rel="noreferrer">
            {result.title}
          </a>
        </div>
      ))}
    </div>
  );
};
