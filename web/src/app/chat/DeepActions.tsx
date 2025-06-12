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
  return <div>Thinking about: {action.thinking}</div>;
};
