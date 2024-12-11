import { User } from "../types";

export interface UsersResponse {
  accepted: User[];
  invited: User[];
  slack_users: User[];
  accepted_pages: number;
  invited_pages: number;
  slack_users_pages: number;
}
