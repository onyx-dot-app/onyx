export interface dictionaryType {
  [key: string]: string;
}
export interface formType extends dictionaryType {
  name: string;
}

export type ActionType = "create" | "createAndSwap";
