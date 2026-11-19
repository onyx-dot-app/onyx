"use client";

import { useEffect } from "react";
import {
  sendAuthRequiredMessage,
  sendMessageToParent,
} from "@/lib/extension/svc";

export function useSendAuthRequiredMessage(): void {
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- posts the auth-required message to the extension's parent window on mount
  useEffect(() => {
    sendAuthRequiredMessage();
  }, []);
}

export function useSendMessageToParent(): void {
  // oxlint-disable-next-line anti-slop/no-unreasoned-state-sync -- posts the ready message to the extension's parent window on mount
  useEffect(() => {
    sendMessageToParent();
  }, []);
}
