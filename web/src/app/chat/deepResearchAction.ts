export type DeepResearchActionPacket = {
  deepResearchAction: "deep_research_action";
  // Union of different tool call stuff
  payload: DeepAction;
};

export type DeepAction =
  | DeepRemoveAction
  | DeepRunCommandAction
  | DeepProcessAction
  | DeepSearchWebAction
  | DeepSendEmailAction
  | DeepThinkingAction;

type DeepRunCommandAction = {
  cmd: string;
  id: string;
  result: string;
  type: "run_command";
  collapsed: boolean;
};

type DeepSearchWebAction = {
  query: string;
  id: string;
  results: {
    title: string;
    url: string;
  }[];
  type: "web_search";
  collapsed: boolean;
};

type DeepRemoveAction = {
  type: "remove";
  id: string;
};

type DeepThinkingAction = {
  type: "thinking";
  id: string;
  thinking: string;
};

type DeepSendEmailAction = {
  type: "email";
  id: string;
  email: string;
};

type DeepProcessAction = {
  type: "process";
  done: boolean;
  id: string;
  description: string;
};

export type DeepActionType<T extends DeepAction["type"]> = Extract<
  DeepAction,
  { type: T }
>;

export type CollapsibleDeepAction = Extract<DeepAction, { collapsed: boolean }>;

export const isCollapsible = (
  action: DeepAction
): action is CollapsibleDeepAction => {
  if ("collapsed" in action) {
    return true;
  }
  return false;
};

export const buildActionPacket = <T extends DeepAction["type"]>(
  type: T,
  data: Omit<DeepActionType<T>, "type">
): DeepResearchActionPacket => {
  return {
    deepResearchAction: "deep_research_action",
    payload: {
      type,
      ...data,
    } as DeepActionType<T>,
  };
};

export const handleNewAction = (prev: DeepAction[], newAction: DeepAction) => {
  switch (newAction.type) {
    case "remove":
      return prev.filter((a) => a.id !== newAction.id);

    // Default: Upsert action
    default:
      const existingAction = prev.find((a) => a.id === newAction.id);
      if (existingAction) {
        return prev.map((a) => (a.id === newAction.id ? newAction : a));
      } else {
        return [...prev, newAction];
      }
  }
};
