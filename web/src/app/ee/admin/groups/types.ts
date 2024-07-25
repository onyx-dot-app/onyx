export interface UserGroupUpdate {
  user_ids: string[];
  cc_pair_ids: number[];
}

export interface UserGroupCreation {
  name: string;
  user_ids: string[];
  cc_pair_ids: number[];
}
