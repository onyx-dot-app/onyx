// RN port of Opal's Tabs (web/lib/opal/src/components/tabs), `pill` variant only — the other two
// have no mobile consumer.
//
// Divergences: scroll arrows dropped (an overflowing touch list is swiped); the indicator sits
// inside the scroll content so it tracks its tab, rather than web's subtract-scrollLeft; the
// baseline gets its width from layout instead of web's ResizeObserver, since the scroll wrapper
// already ends where `rightChildren` begins; RN `Animated`, not reanimated, so a tab strip stays
// renderable under jest.
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Animated, Pressable, ScrollView, View } from "react-native";

import { Icon } from "@/components/ui/icon";
import { Spinner } from "@/components/ui/spinner";
import { Text } from "@/components/ui/text";
import type { IconFunctionComponent } from "@/icons/types";
import { cn } from "@/lib/utils";

// Off the token scale, so it can't be a class.
const LIST_BOTTOM_PADDING = 5;
// No top padding to match: Opal's `pt-1` is on its no-scroll-arrows branch, and both call sites here
// use the scrollable one.
const TRIGGER_GAP = 8;
const INDICATOR_HEIGHT = 2;
const TRIGGER_ICON_SIZE = 14;
const TRIGGER_SPINNER_SIZE = 12;
const INDICATOR_DURATION_MS = 200;

interface TriggerLayout {
  x: number;
  width: number;
}

interface TabsContextValue {
  value: string;
  onValueChange: (value: string) => void;
  setTriggerLayout: (value: string, layout: TriggerLayout) => void;
}

const TabsContext = createContext<TabsContextValue | null>(null);

function useTabsContext(): TabsContextValue {
  const context = useContext(TabsContext);
  if (!context) {
    throw new Error("Tabs.List / Tabs.Trigger must be rendered inside <Tabs>");
  }
  return context;
}

// Split from TabsContext so a Trigger reporting its layout doesn't re-render every other Trigger.
const LayoutsContext = createContext<Record<string, TriggerLayout>>({});

export interface TabsProps {
  value: string;
  onValueChange: (value: string) => void;
  children: ReactNode;
}

function TabsRoot({ value, onValueChange, children }: TabsProps) {
  // Held here, not in the Triggers that measure them: the List's indicator is what consumes them.
  const [layouts, setLayouts] = useState<Record<string, TriggerLayout>>({});

  const setTriggerLayout = useCallback(
    (triggerValue: string, layout: TriggerLayout) => {
      setLayouts((prev) => {
        const current = prev[triggerValue];
        if (current?.x === layout.x && current?.width === layout.width) {
          return prev;
        }
        return { ...prev, [triggerValue]: layout };
      });
    },
    [],
  );

  const context = useMemo(
    () => ({ value, onValueChange, setTriggerLayout }),
    [value, onValueChange, setTriggerLayout],
  );

  return (
    <TabsContext.Provider value={context}>
      <LayoutsContext.Provider value={layouts}>
        <View className="w-full">{children}</View>
      </LayoutsContext.Provider>
    </TabsContext.Provider>
  );
}

export interface TabsListProps {
  children: ReactNode;
  // Pinned right, outside the scroll area, so it stays put as the strip scrolls.
  rightChildren?: ReactNode;
}

function TabsList({ children, rightChildren }: TabsListProps) {
  const { value } = useTabsContext();
  const layouts = useContext(LayoutsContext);
  const active = layouts[value];

  // useMemo, not useRef: these are read during render to build the style, and the refs lint forbids
  // reading a ref there. Same shape `Spinner` uses.
  const left = useMemo(() => new Animated.Value(0), []);
  const width = useMemo(() => new Animated.Value(0), []);
  const hasAnimated = useRef(false);

  useEffect(() => {
    if (!active) return;
    // First placement snaps — sliding in from x=0 would read as a stray animation on mount.
    if (!hasAnimated.current) {
      hasAnimated.current = true;
      left.setValue(active.x);
      width.setValue(active.width);
      return;
    }
    Animated.parallel([
      Animated.timing(left, {
        toValue: active.x,
        duration: INDICATOR_DURATION_MS,
        useNativeDriver: false,
      }),
      Animated.timing(width, {
        toValue: active.width,
        duration: INDICATOR_DURATION_MS,
        useNativeDriver: false,
      }),
    ]).start();
  }, [active, left, width]);

  return (
    <View className="w-full flex-row items-center overflow-hidden bg-background-tint-00">
      <View className="min-w-0 flex-1">
        {/* Declared before the strip so the indicator paints over it; RN has no z-index, which is
            how Opal orders these two. */}
        <View className="absolute bottom-0 left-0 right-0 h-[1px] bg-border-02" />
        <ScrollView
          horizontal
          showsHorizontalScrollIndicator={false}
          // All inline: NativeWind maps `contentContainerClassName` onto this same prop, so passing
          // both would have them overwrite each other.
          contentContainerStyle={{
            flexDirection: "row",
            alignItems: "center",
            gap: TRIGGER_GAP,
            paddingBottom: LIST_BOTTOM_PADDING,
          }}
        >
          {children}
          {active ? (
            <Animated.View
              className="absolute bottom-0 bg-background-tint-inverted-03"
              style={{ height: INDICATOR_HEIGHT, left, width }}
            />
          ) : null}
        </ScrollView>
      </View>
      {rightChildren ? <View className="shrink-0">{rightChildren}</View> : null}
    </View>
  );
}

export interface TabsTriggerProps {
  value: string;
  children: string;
  icon?: IconFunctionComponent;
  isLoading?: boolean;
}

function TabsTrigger({
  value,
  children,
  icon,
  isLoading = false,
}: TabsTriggerProps) {
  const {
    value: activeValue,
    onValueChange,
    setTriggerLayout,
  } = useTabsContext();
  const selected = value === activeValue;
  const foreground = selected ? "text-text-inverted-05" : "text-text-03";

  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected }}
      onPress={() => onValueChange(value)}
      onLayout={(event) => {
        const { x, width } = event.nativeEvent.layout;
        setTriggerLayout(value, { x, width });
      }}
      className={cn(
        "flex-row items-center justify-center rounded-08 p-4",
        selected ? "bg-background-tint-inverted-03" : "bg-background-tint-00",
      )}
    >
      {icon ? (
        <View className="p-2">
          <Icon as={icon} size={TRIGGER_ICON_SIZE} className={foreground} />
        </View>
      ) : null}
      <View className="px-2">
        <Text
          font="secondary-action"
          color={selected ? "text-inverted-05" : "text-03"}
          nowrap
        >
          {children}
        </Text>
      </View>
      {isLoading ? (
        <View className="ml-4">
          <Spinner size={TRIGGER_SPINNER_SIZE} className={foreground} />
        </View>
      ) : null}
    </Pressable>
  );
}

export const Tabs = Object.assign(TabsRoot, {
  List: TabsList,
  Trigger: TabsTrigger,
});
