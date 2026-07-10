"use client";

import { useEffect } from "react";
import {
  sendAuthRequiredMessage,
  sendMessageToParent,
} from "@/lib/extension/svc";

export function useSendAuthRequiredMessage(): void {
  useEffect(() => {
    sendAuthRequiredMessage();
  }, []);
}

export function useSendMessageToParent(): void {
  useEffect(() => {
    sendMessageToParent();
  }, []);
}
