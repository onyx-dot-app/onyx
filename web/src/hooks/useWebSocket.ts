import { useState, useRef, useCallback, useEffect } from "react";

export type WebSocketStatus =
  | "connecting"
  | "connected"
  | "disconnected"
  | "error";

export interface UseWebSocketOptions<T> {
  /** URL to connect to */
  url: string;
  /** Called when a message is received */
  onMessage?: (data: T) => void;
  /** Called when connection opens */
  onOpen?: () => void;
  /** Called when connection closes */
  onClose?: () => void;
  /** Called on error */
  onError?: (error: Event) => void;
  /** Auto-connect on mount */
  autoConnect?: boolean;
}

export interface UseWebSocketReturn<T> {
  /** Current connection status */
  status: WebSocketStatus;
  /** Send JSON data */
  sendJson: (data: T) => void;
  /** Send binary data */
  sendBinary: (data: Blob | ArrayBuffer) => void;
  /** Connect to WebSocket */
  connect: () => Promise<void>;
  /** Disconnect from WebSocket */
  disconnect: () => void;
}

export function useWebSocket<TReceive = unknown, TSend = unknown>({
  url,
  onMessage,
  onOpen,
  onClose,
  onError,
  autoConnect = false,
}: UseWebSocketOptions<TReceive>): UseWebSocketReturn<TSend> {
  const [status, setStatus] = useState<WebSocketStatus>("disconnected");
  const wsRef = useRef<WebSocket | null>(null);
  const onMessageRef = useRef(onMessage);
  const onOpenRef = useRef(onOpen);
  const onCloseRef = useRef(onClose);
  const onErrorRef = useRef(onError);

  // Keep refs updated
  useEffect(() => {
    onMessageRef.current = onMessage;
    onOpenRef.current = onOpen;
    onCloseRef.current = onClose;
    onErrorRef.current = onError;
  }, [onMessage, onOpen, onClose, onError]);

  const connect = useCallback(async (): Promise<void> => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    setStatus("connecting");

    return new Promise((resolve, reject) => {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      const timeout = setTimeout(() => {
        ws.close();
        reject(new Error("WebSocket connection timeout"));
      }, 10000);

      ws.onopen = () => {
        clearTimeout(timeout);
        setStatus("connected");
        onOpenRef.current?.();
        resolve();
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as TReceive;
          onMessageRef.current?.(data);
        } catch {
          // Non-JSON message, ignore or handle differently
        }
      };

      ws.onclose = () => {
        setStatus("disconnected");
        onCloseRef.current?.();
        wsRef.current = null;
      };

      ws.onerror = (error) => {
        clearTimeout(timeout);
        setStatus("error");
        onErrorRef.current?.(error);
        reject(new Error("WebSocket connection failed"));
      };
    });
  }, [url]);

  const disconnect = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setStatus("disconnected");
  }, []);

  const sendJson = useCallback((data: TSend) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const sendBinary = useCallback((data: Blob | ArrayBuffer) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(data);
    }
  }, []);

  // Auto-connect if enabled
  useEffect(() => {
    if (autoConnect) {
      connect().catch(() => {
        // Error handled via onError callback
      });
    }
    return () => {
      disconnect();
    };
  }, [autoConnect, connect, disconnect]);

  return {
    status,
    sendJson,
    sendBinary,
    connect,
    disconnect,
  };
}
