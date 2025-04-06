export enum UserRole {
  ADMIN = 'ADMIN',
  CURATOR = 'CURATOR',
  BASIC = 'BASIC',
  DEMO = 'DEMO'
}

export interface User {
  id: string;
  email: string;
  is_active: boolean;
  role: UserRole;
  created_at: string;
  preferences: {
    [key: string]: any;
  };
}

export interface UserContextType {
  user: User | null;
  isLoading: boolean;
  isAdmin: boolean;
  isCurator: boolean;
  isDemo: boolean;
  isDemoExpired: boolean;
  updateUserPreferences: (preferences: Partial<User>) => void;
  refreshUser: () => void;
} 