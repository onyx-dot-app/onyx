// Replaces web's hover SourceTagDetailsCard (Radix tooltip) with a tap-to-open
// bottom-sheet, plus a context to open it from any inline CitationPill.

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { View, Pressable, Linking } from "react-native";
import { BottomSheetView } from "@gorhom/bottom-sheet";

import { BottomSheet, type BottomSheetRef, Text } from "@/components/opal";
import { useThemeColors } from "@/theme/ThemeProvider";
import { radii } from "@/theme/generated/radii";
import {
  SvgArrowLeft,
  SvgChevronRight,
  SvgExternalLink,
} from "@/components/icons";
import { SourceIcon } from "@/components/message/sources/SourceIcon";
import type { SourceInfo } from "@/components/message/sources/sourceInfo";

interface CitationSheetContextValue {
  present: (sources: SourceInfo[], startIndex?: number) => void;
}

const CitationSheetContext = createContext<CitationSheetContextValue | null>(null);

export function useCitationSheet(): CitationSheetContextValue {
  const ctx = useContext(CitationSheetContext);
  if (!ctx) {
    // No-op fallback so a stray pill outside the provider never crashes.
    return { present: () => undefined };
  }
  return ctx;
}

function timeAgo(value: string | null | undefined, now: number): string | null {
  if (!value) return null;
  const t = Date.parse(value);
  if (Number.isNaN(t)) return null;
  const diff = Math.max(0, now - t);
  const sec = Math.floor(diff / 1000);
  const min = Math.floor(sec / 60);
  const hr = Math.floor(min / 60);
  const day = Math.floor(hr / 24);
  if (day > 30) return new Date(t).toLocaleDateString();
  if (day >= 1) return `${day} day${day > 1 ? "s" : ""} ago`;
  if (hr >= 1) return `${hr} hour${hr > 1 ? "s" : ""} ago`;
  if (min >= 1) return `${min} minute${min > 1 ? "s" : ""} ago`;
  return "just now";
}

interface CitationSheetProviderProps {
  children: ReactNode;
  nowMs?: number;
}

export function CitationSheetProvider({ children, nowMs }: CitationSheetProviderProps) {
  const sheetRef = useRef<BottomSheetRef>(null);
  const colors = useThemeColors();
  const [sources, setSources] = useState<SourceInfo[]>([]);
  const [index, setIndex] = useState(0);

  const present = useCallback((next: SourceInfo[], startIndex = 0) => {
    if (next.length === 0) return;
    setSources(next);
    setIndex(Math.min(Math.max(0, startIndex), next.length - 1));
    sheetRef.current?.present();
  }, []);

  const ctx = useMemo<CitationSheetContextValue>(() => ({ present }), [present]);

  const active = sources[index];
  const multi = sources.length > 1;
  const date = active ? timeAgo(active.date, nowMs ?? 0) : null;

  return (
    <CitationSheetContext.Provider value={ctx}>
      {children}
      <BottomSheet ref={sheetRef} snapPoints={["38%"]} enablePanDownToClose>
        <BottomSheetView style={{ paddingBottom: 24 }}>
          {active && (
            <View style={{ paddingHorizontal: 16, paddingTop: 4 }}>
              {multi && (
                <View
                  style={{
                    flexDirection: "row",
                    alignItems: "center",
                    justifyContent: "space-between",
                    backgroundColor: colors["background-tint-01"],
                    borderRadius: radii["08"],
                    paddingHorizontal: 8,
                    paddingVertical: 6,
                    marginBottom: 12,
                  }}
                >
                  <Pressable
                    onPress={() => setIndex((i) => Math.max(0, i - 1))}
                    hitSlop={8}
                    disabled={index === 0}
                    style={{ opacity: index === 0 ? 0.4 : 1, padding: 4 }}
                  >
                    <SvgArrowLeft size={18} color="text-04" />
                  </Pressable>
                  <Text font="secondary-body" color="text-03">
                    {index + 1}/{sources.length}
                  </Text>
                  <Pressable
                    onPress={() =>
                      setIndex((i) => Math.min(sources.length - 1, i + 1))
                    }
                    hitSlop={8}
                    disabled={index === sources.length - 1}
                    style={{
                      opacity: index === sources.length - 1 ? 0.4 : 1,
                      padding: 4,
                    }}
                  >
                    <SvgChevronRight size={18} color="text-04" />
                  </Pressable>
                </View>
              )}

              <View
                style={{ flexDirection: "row", alignItems: "center", gap: 8 }}
              >
                <SourceIcon
                  sourceType={active.sourceType}
                  isInternet={active.isInternet}
                  size={18}
                  color="text-04"
                />
                <View style={{ flex: 1, minWidth: 0 }}>
                  <Text font="main-ui-action" color="text-04" numberOfLines={1}>
                    {active.title}
                  </Text>
                </View>
              </View>

              {date && (
                <View style={{ marginTop: 8 }}>
                  <Text font="secondary-body" color="text-02">
                    {date}
                  </Text>
                </View>
              )}

              {!!active.description && (
                <View style={{ marginTop: 8 }}>
                  <Text font="secondary-body" color="text-03" numberOfLines={4}>
                    {active.description}
                  </Text>
                </View>
              )}

              {!!active.sourceUrl && (
                <Pressable
                  onPress={() => {
                    if (active.sourceUrl) void Linking.openURL(active.sourceUrl);
                  }}
                  style={{
                    marginTop: 16,
                    flexDirection: "row",
                    alignItems: "center",
                    gap: 6,
                    alignSelf: "flex-start",
                    backgroundColor: colors["background-tint-02"],
                    borderRadius: radii["08"],
                    paddingHorizontal: 12,
                    paddingVertical: 8,
                  }}
                >
                  <SvgExternalLink size={16} color="action-text-link-05" />
                  <Text font="secondary-action" color="action-text-link-05">
                    Open
                  </Text>
                </Pressable>
              )}
            </View>
          )}
        </BottomSheetView>
      </BottomSheet>
    </CitationSheetContext.Provider>
  );
}
