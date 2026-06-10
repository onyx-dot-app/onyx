// Bridges device connectivity (via @react-native-community/netinfo) into
// TanStack Query's onlineManager. Without this, TanStack assumes it's always
// online: offline queries error and retry in a loop, and `refetchOnReconnect`
// has nothing to trigger it.
import NetInfo from "@react-native-community/netinfo";
import { onlineManager } from "@tanstack/react-query";

// Call once at app startup; returns an unsubscribe for cleanup.
export function bindOnlineManager(): () => void {
  return NetInfo.addEventListener((state) => {
    // `isInternetReachable` is null while NetInfo is still determining
    // reachability — treat that as online to avoid false offline flashes.
    onlineManager.setOnline(
      Boolean(state.isConnected) && state.isInternetReachable !== false,
    );
  });
}
