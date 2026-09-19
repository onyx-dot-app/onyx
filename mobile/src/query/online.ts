// Without this, TanStack assumes always-online and refetchOnReconnect never fires.
import NetInfo from "@react-native-community/netinfo";
import { onlineManager } from "@tanstack/react-query";

export function bindOnlineManager(): () => void {
  return NetInfo.addEventListener((state) => {
    // isInternetReachable is null until NetInfo resolves; treat as online.
    onlineManager.setOnline(
      Boolean(state.isConnected) && state.isInternetReachable !== false,
    );
  });
}
