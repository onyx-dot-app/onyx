"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { useDebouncedValue } from "@opal/hooks";
import {
  discoverPKCESupport,
  initiateOAuthTest,
  type OAuthTestRequest,
  type PKCESupportStatus,
} from "@/lib/oauth/api";
import {
  isOAuthTestMessage,
  OAUTH_TEST_ACTIVE_KEY,
  oauthTestStorageKey,
  oauthTestChannelName,
  type OAuthTestResult,
} from "@/lib/oauth/testConnection";

export function isHttpsEndpoint(value: string): boolean {
  try {
    return new URL(value).protocol === "https:";
  } catch {
    return false;
  }
}

export function usePKCESupport(authorizationUrl: string, tokenUrl: string) {
  const endpoints = JSON.stringify([authorizationUrl.trim(), tokenUrl.trim()]);
  const debounced = useDebouncedValue(endpoints, 500);
  const valid = isHttpsEndpoint(authorizationUrl) && isHttpsEndpoint(tokenUrl);
  const pendingEdit = endpoints !== debounced;
  const { data, error, isLoading } = useSWR<PKCESupportStatus, Error>(
    valid && !pendingEdit
      ? ["oauth-pkce-support", authorizationUrl.trim(), tokenUrl.trim()]
      : null,
    ([, authorize, token]: [string, string, string]) =>
      discoverPKCESupport(authorize, token),
    { revalidateOnFocus: false, shouldRetryOnError: false }
  );
  return valid
    ? pendingEdit || isLoading
      ? "checking"
      : error
        ? "unknown"
        : (data ?? "unknown")
    : "idle";
}

type TestStatus =
  | OAuthTestResult
  | { status: "idle" | "pending" | "blocked" | "closed" | "stale" };
interface ActiveTest {
  popup: Window;
  state?: string;
  controller: AbortController;
  dispose: () => void;
}

export function useOAuthConnectionTest(request: OAuthTestRequest) {
  const requestKey = JSON.stringify(request);
  const [outcome, setOutcome] = useState<{
    requestKey: string;
    result: TestStatus;
  } | null>(null);
  const active = useRef<ActiveTest | null>(null);

  const cancel = useCallback(() => {
    const attempt = active.current;
    active.current = null;
    if (attempt) {
      attempt.controller.abort();
      attempt.dispose();
      attempt.popup.close();
    }
  }, []);

  useEffect(() => {
    setOutcome((current) =>
      current?.result.status === "pending" && current.requestKey !== requestKey
        ? { ...current, result: { status: "interrupted" } }
        : current
    );
    return cancel;
  }, [requestKey, cancel]);

  const start = useCallback(async () => {
    cancel();
    const popup = window.open("", "_blank", "popup,width=650,height=760");
    if (!popup) {
      setOutcome({ requestKey, result: { status: "blocked" } });
      return;
    }
    setOutcome({ requestKey, result: { status: "pending" } });
    const attempt: ActiveTest = {
      popup,
      controller: new AbortController(),
      dispose: () => {},
    };
    active.current = attempt;
    const finish = (result: TestStatus) => {
      if (active.current !== attempt) return;
      setOutcome({ requestKey, result });
      cancel();
    };
    const receive = (event: MessageEvent<unknown>) => {
      if (
        event.origin !== window.location.origin ||
        event.source !== popup ||
        !isOAuthTestMessage(event.data) ||
        event.data.state !== attempt.state
      )
        return;
      finish(event.data.result);
    };
    let channel: BroadcastChannel | null = null;
    let reportedClosed = false;
    const startedAt = Date.now();
    const timer = window.setInterval(() => {
      if (Date.now() - startedAt > 10 * 60 * 1000) {
        finish({ status: "interrupted" });
      } else if (popup.closed && !reportedClosed) {
        // Provider isolation can sever the opener while the popup remains open.
        reportedClosed = true;
        if (channel) setOutcome({ requestKey, result: { status: "closed" } });
        else finish({ status: "closed" });
      }
    }, 500);
    window.addEventListener("message", receive);
    attempt.dispose = () => {
      channel?.close();
      window.clearInterval(timer);
      window.removeEventListener("message", receive);
    };
    try {
      const response = await initiateOAuthTest(
        request,
        attempt.controller.signal
      );
      if (active.current !== attempt) return;
      attempt.state = response.state;
      if (typeof BroadcastChannel !== "undefined") {
        try {
          channel = new BroadcastChannel(oauthTestChannelName(response.state));
          channel.onmessage = (event: MessageEvent<unknown>) => {
            if (
              isOAuthTestMessage(event.data) &&
              event.data.state === attempt.state
            )
              finish(event.data.result);
          };
        } catch {
          // Restricted browsers can still report through the opener.
        }
      }
      popup.sessionStorage.setItem(OAUTH_TEST_ACTIVE_KEY, response.state);
      popup.sessionStorage.setItem(
        oauthTestStorageKey(response.state),
        "pending"
      );
      popup.location.href = response.authorization_url;
    } catch {
      finish({ status: "failed" });
    }
  }, [request, requestKey, cancel]);

  const result: TestStatus =
    outcome && outcome.requestKey === requestKey
      ? outcome.result
      : { status: outcome ? "stale" : "idle" };
  return { result, start };
}
