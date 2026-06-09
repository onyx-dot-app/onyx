// Bridges React Native's AppState into TanStack Query's focusManager so that
// queries can refetch when the app returns to the foreground (the mobile
// equivalent of browser window-focus refetching). Zero extra dependencies.
import { AppState, type AppStateStatus } from "react-native";
import { focusManager } from "@tanstack/react-query";

// Call once at app startup; returns an unsubscribe for cleanup.
export function bindAppStateFocus(): () => void {
  function onChange(status: AppStateStatus): void {
    focusManager.setFocused(status === "active");
  }
  const subscription = AppState.addEventListener("change", onChange);
  return () => subscription.remove();
}
