import { TypedFile } from "@/lib/connectors/fileTypes";

export interface dictionaryType {
  [key: string]: string | TypedFile;
}
export interface formType extends dictionaryType {
  name: string;
}

export type ActionType = "create" | "createAndSwap";
