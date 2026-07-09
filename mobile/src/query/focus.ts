// RN AppState -> focusManager: the mobile equivalent of browser window-focus refetching.
import { AppState, type AppStateStatus } from "react-native";
import { focusManager } from "@tanstack/react-query";

export function bindAppStateFocus(): () => void {
  function onChange(status: AppStateStatus): void {
    focusManager.setFocused(status === "active");
  }
  const subscription = AppState.addEventListener("change", onChange);
  return () => subscription.remove();
}
