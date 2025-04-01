export interface UserGroupUpdate {
  user_ids: string[];
  new_user_emails?: string[];
  cc_pair_ids: number[];
}

export interface SetCuratorRequest {
  user_id: string;
  is_curator: boolean;
}

export interface UserGroupCreation {
  name: string;
  user_ids: string[];
  new_user_emails?: string[];
  cc_pair_ids: number[];
}
