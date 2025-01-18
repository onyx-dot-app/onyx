import { ChatSession } from "../interfaces";

export interface Folder {
  folder_id?: number;
  folder_name: string;
  display_priority: number;
  chat_sessions: ChatSession[];
}
