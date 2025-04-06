import React, { useState, useCallback, useMemo, createContext } from 'react';
import { User, UserRole } from '../types/User';

interface UserContextType {
  user: User | null;
  isLoading: boolean;
  isAdmin: boolean;
  isCurator: boolean;
  isDemo: boolean;
  isDemoExpired: boolean;
  updateUserPreferences: (preferences: Partial<User>) => void;
  refreshUser: () => void;
}

export const UserContext = createContext<UserContextType>({
  user: null,
  isLoading: true,
  isAdmin: false,
  isCurator: false,
  isDemo: false,
  isDemoExpired: false,
  updateUserPreferences: () => {},
  refreshUser: () => {},
});

export const UserProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const getIsDemoExpired = useCallback((user: User) => {
    if (user.role !== UserRole.DEMO) return false;
    const demoExpiry = new Date(user.created_at);
    demoExpiry.setDate(demoExpiry.getDate() + 7);
    return new Date() > demoExpiry;
  }, []);

  const isAdmin = useMemo(() => user?.role === UserRole.ADMIN, [user]);
  const isCurator = useMemo(() => user?.role === UserRole.CURATOR, [user]);
  const isDemo = useMemo(() => user?.role === UserRole.DEMO, [user]);
  const isDemoExpired = useMemo(() => user ? getIsDemoExpired(user) : false, [user, getIsDemoExpired]);

  const updateUserPreferences = useCallback((preferences: Partial<User>) => {
    if (user) {
      setUser({ ...user, ...preferences });
    }
  }, [user]);

  const refreshUser = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/user');
      const userData = await response.json();
      setUser(userData);
    } catch (error) {
      console.error('Failed to refresh user:', error);
    } finally {
      setIsLoading(false);
    }
  }, []);

  const value = useMemo(
    () => ({
      user,
      isLoading,
      isAdmin,
      isCurator,
      isDemo,
      isDemoExpired,
      updateUserPreferences,
      refreshUser,
    }),
    [user, isLoading, isAdmin, isCurator, isDemo, isDemoExpired, updateUserPreferences, refreshUser]
  );

  return (
    <UserContext.Provider value={value}>
      {children}
    </UserContext.Provider>
  );
}; 