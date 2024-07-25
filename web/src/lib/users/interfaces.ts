import { User } from "../types";

export interface UsersResponse {
  accepted: User[];
  invited: User[];
  accepted_pages: number;
  invited_pages: number;
}
