import { Packet } from "@/app/app/services/streamingModels";
import { FeedbackType } from "@/app/app/interfaces";

export interface MultiModelResponse {
  modelIndex: number;
  provider: string;
  modelName: string;
  displayName: string;
  packets: Packet[];
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
