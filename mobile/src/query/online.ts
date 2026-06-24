// Without this, TanStack assumes always-online: offline queries retry-loop and refetchOnReconnect never fires.
import NetInfo from "@react-native-community/netinfo";
import { onlineManager } from "@tanstack/react-query";

// Call once at app startup.
export function bindOnlineManager(): () => void {
  return NetInfo.addEventListener((state) => {
    // isInternetReachable is null until NetInfo resolves; treat as online to avoid false offline flashes.
    onlineManager.setOnline(
      Boolean(state.isConnected) && state.isInternetReachable !== false,
    );
  });
}
