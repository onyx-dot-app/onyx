import { useCallback, useMemo } from "react";
import {
  MessageSubmissionService,
  MessageSubmissionDependencies,
  MessageSubmissionParams,
} from "../services/messageSubmissionService";

export function useMessageSubmission(
  dependencies: MessageSubmissionDependencies
) {
  const service = useMemo(
    () => new MessageSubmissionService(dependencies),
    [dependencies]
  );

  const submitMessage = useCallback(
    async (params: MessageSubmissionParams = {}) => {
      return await service.submitMessage(params);
    },
    [service]
  );

  return { submitMessage };
}
