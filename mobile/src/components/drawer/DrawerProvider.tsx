import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import {
  useSharedValue,
  withTiming,
  type SharedValue,
} from "react-native-reanimated";

// `progress` (0 closed → 1 open) is a Reanimated shared value driven on the UI
// thread by both the timing animations and the pan gesture; `isOpen` mirrors it in
// React state for non-animated consumers (e.g. gating the backdrop's tap-to-close).
const DRAWER_ANIM_MS = 240;

interface DrawerContextValue {
  progress: SharedValue<number>;
  isOpen: boolean;
  open: () => void;
  close: () => void;
  toggle: () => void;
}

const DrawerContext = createContext<DrawerContextValue | null>(null);

export function DrawerProvider({ children }: { children: ReactNode }) {
  const progress = useSharedValue(0);
  const [isOpen, setIsOpen] = useState(false);

  const open = useCallback(() => {
    setIsOpen(true);
    progress.value = withTiming(1, { duration: DRAWER_ANIM_MS });
  }, [progress]);

  const close = useCallback(() => {
    setIsOpen(false);
    progress.value = withTiming(0, { duration: DRAWER_ANIM_MS });
  }, [progress]);

  const toggle = useCallback(() => {
    if (isOpen) close();
    else open();
  }, [isOpen, open, close]);

  const value = useMemo(
    () => ({ progress, isOpen, open, close, toggle }),
    [progress, isOpen, open, close, toggle],
  );

  return (
    <DrawerContext.Provider value={value}>{children}</DrawerContext.Provider>
  );
}

export function useDrawer(): DrawerContextValue {
  const ctx = useContext(DrawerContext);
  if (!ctx) {
    throw new Error("useDrawer must be used within a <DrawerProvider>.");
  }
  return ctx;
}
