export type FeedbackType = "like" | "dislike";
export type ChatState = "input" | "loading" | "streaming" | "toolBuilding";
export interface RegenerationState {
  regenerating: boolean;
  finalMessageIndex: number;
}
