export type DeepResearchActionPacket = {
  deepResearchAction: "deep_research_action";
  // Union of different tool call stuff
  payload: DeepAction;
};

export type DeepAction = DeepRemoveAction | DeepRunCommandAction;

type DeepRunCommandAction = {
  cmd: string;
  id: string;
  result: string;
  type: "run_command";
};

type DeepRemoveAction = {
  type: "remove";
  id: string;
};

export const handleNewAction = (prev: DeepAction[], newAction: DeepAction) => {
  // TODO: check for remove action
  switch (newAction.type) {
    case "remove":
      return prev.filter((a) => a.id !== newAction.id);

    // Default: Upsert action
    default:
      const existingAction = prev.find((a) => a.id === newAction.id);
      if (existingAction) {
        return prev.map((a) =>
          a.id === newAction.id ? { ...a, result: newAction.result } : a
        );
      } else {
        return [...prev, newAction];
      }
  }
};
