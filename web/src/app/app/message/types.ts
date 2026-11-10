import { Packet } from "@/app/app/services/streamingModels";
import { AcceptedUserMessage, FeedbackType } from "@/app/app/types";

export interface MultiModelResponse {
  modelIndex: number;
  provider: string;
  modelName: string;
  displayName: string;
  packets: Packet[];
  acceptedUserMessages?: AcceptedUserMessage[];
  packetCount: number;
  nodeId: number;
  messageId?: number;

  currentFeedback?: FeedbackType | null;
  isGenerating?: boolean;

  // Error state (when this model failed)
  errorMessage?: string | null;
  errorCode?: string | null;
  isRetryable?: boolean;
  errorStackTrace?: string | null;
  errorDetails?: Record<string, any> | null;
}
