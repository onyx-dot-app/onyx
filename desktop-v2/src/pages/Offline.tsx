import { useEffect, useState } from "react";
import { listen } from "@tauri-apps/api/event";
import { Button, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { mount } from "@/lib/mount";
import { ErrorText, WindowFrame } from "@/lib/WindowFrame";
import {
  changeServer,
  errorMessage,
  getOfflineStatus,
  OFFLINE_STATUS_EVENT,
  retryConnection,
  type OfflineStatus,
  type Unreachable,
} from "@/lib/ipc";

function reasonText(reason: Unreachable): string {
  switch (reason.kind) {
    case "noNetwork":
      return "Your computer is not connected to a network.";
    case "dns":
      return "The server name could not be found.";
    case "tls":
      return (
        "The server's security certificate could not be verified. A company proxy that " +
        "inspects secure traffic, or a missing company root certificate, often causes " +
        "this. Contact your IT team."
      );
    case "timeout":
      return "The server took too long to answer.";
    case "refused":
      return "The server is not accepting connections.";
    case "serverError":
      return `The server returned an error (${reason.status}).`;
    case "unknown":
      return "The connection to the server failed.";
  }
}

function Offline() {
  const [status, setStatus] = useState<OfflineStatus | null>(null);
  const [retryAt, setRetryAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [online, setOnline] = useState(() => navigator.onLine);
  const [error, setError] = useState<string | null>(null);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const apply = (next: OfflineStatus) => {
      setStatus(next);
      setRetryAt(next.nextRetryMs === null ? null : Date.now() + next.nextRetryMs);
    };
    const unlisten = listen<OfflineStatus>(OFFLINE_STATUS_EVENT, (event) => apply(event.payload));
    void getOfflineStatus().then((current) => {
      if (current) apply(current);
    });
    // The network is back: check now instead of waiting for the next step.
    const onOnline = () => {
      setOnline(true);
      void retryConnection();
    };
    const onOffline = () => setOnline(false);
    window.addEventListener("online", onOnline);
    window.addEventListener("offline", onOffline);
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    return () => {
      void unlisten.then((stop) => stop());
      window.removeEventListener("online", onOnline);
      window.removeEventListener("offline", onOffline);
      window.clearInterval(tick);
    };
  }, []);

  function onRetry() {
    setError(null);
    setStatus((current) => (current ? { ...current, checking: true } : current));
    setRetryAt(null);
    retryConnection().catch((e) => setError(errorMessage(e)));
  }

  async function onChangeServer() {
    setError(null);
    setLeaving(true);
    try {
      await changeServer();
    } catch (e) {
      setError(errorMessage(e));
      setLeaving(false);
    }
  }

  const host = status?.host ?? "the server";
  const reason = !online
    ? reasonText({ kind: "noNetwork" })
    : status
      ? reasonText(status.reason)
      : undefined;
  const checking = status?.checking ?? false;
  const seconds = retryAt === null ? null : Math.max(0, Math.ceil((retryAt - now) / 1000));

  return (
    <WindowFrame title={`Can't reach ${host}`} subtitle={reason}>
      <Section gap={4} alignItems="stretch" height="fit">
        <div role="status">
          <Text font="secondary-body" color="text-03">
            {checking
              ? "Checking the connection…"
              : seconds !== null
                ? `Onyx tries again in ${seconds}s and opens when the server answers.`
                : "Onyx opens when the server answers."}
          </Text>
        </div>
        <ErrorText message={error} />
        <Section flexDirection="row" justifyContent="between" height="fit">
          {status?.serverLocked ? (
            <span />
          ) : (
            <Button prominence="tertiary" disabled={leaving} onClick={() => void onChangeServer()}>
              Change server
            </Button>
          )}
          <Button autoFocus disabled={checking || leaving} onClick={onRetry}>
            {checking ? "Checking…" : "Retry"}
          </Button>
        </Section>
      </Section>
    </WindowFrame>
  );
}

mount(<Offline />);
