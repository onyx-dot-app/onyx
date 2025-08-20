interface UseMessageSwitchingProps {
  messageId?: number | null;
  otherMessagesCanSwitchTo?: number[];
  onMessageSelection?: (messageId: number) => void;
}

interface UseMessageSwitchingReturn {
  currentMessageInd: number | undefined;
  includeMessageSwitcher: boolean;
  getPreviousMessage: () => number | undefined;
  getNextMessage: () => number | undefined;
}

export function useMessageSwitching({
  messageId,
  otherMessagesCanSwitchTo,
  onMessageSelection,
}: UseMessageSwitchingProps): UseMessageSwitchingReturn {
  // Calculate message switching state
  const currentMessageInd = messageId
    ? otherMessagesCanSwitchTo?.indexOf(messageId)
    : undefined;

  const includeMessageSwitcher =
    currentMessageInd !== undefined &&
    onMessageSelection !== undefined &&
    otherMessagesCanSwitchTo !== undefined &&
    otherMessagesCanSwitchTo.length > 1;

  const getPreviousMessage = () => {
    if (
      currentMessageInd !== undefined &&
      currentMessageInd > 0 &&
      otherMessagesCanSwitchTo
    ) {
      return otherMessagesCanSwitchTo[currentMessageInd - 1];
    }
    return undefined;
  };

  const getNextMessage = () => {
    if (
      currentMessageInd !== undefined &&
      currentMessageInd < (otherMessagesCanSwitchTo?.length || 0) - 1 &&
      otherMessagesCanSwitchTo
    ) {
      return otherMessagesCanSwitchTo[currentMessageInd + 1];
    }
    return undefined;
  };

  return {
    currentMessageInd,
    includeMessageSwitcher,
    getPreviousMessage,
    getNextMessage,
  };
}
