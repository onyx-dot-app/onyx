export interface UserCounter {
  key: string;
  title: string;
  description: string;
  hint: string;
  icon: string;
  target: number;
  current: number;
  completed_at: string | null;
  acknowledged: boolean;
}
