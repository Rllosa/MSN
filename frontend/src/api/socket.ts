import { useEffect, useRef } from "react";
import { useAuthStore } from "../store/auth";

type NewMessagePayload = {
  type: "new_message";
  conversation_id: string;
};

const WS_URL = (() => {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws`;
})();

const RECONNECT_DELAY_MS = [1000, 2000, 5000, 10000, 30000];

/**
 * Connects to the backend WebSocket, authenticates with the JWT access token,
 * and calls `onNewMessage(conversationId)` on each new_message event.
 *
 * Auto-reconnects with backoff. Falls back to the 30s polling interval in
 * InboxPage if the connection cannot be established.
 */
export function useInboxSocket(onNewMessage: (convId: string) => void) {
  const onNewMessageRef = useRef(onNewMessage);
  onNewMessageRef.current = onNewMessage;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let reconnectAttempt = 0;
    let stopped = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

    function connect() {
      if (stopped) return;
      const token = useAuthStore.getState().accessToken;
      if (!token) return; // not logged in — skip

      ws = new WebSocket(WS_URL);

      ws.onopen = () => {
        reconnectAttempt = 0;
        ws!.send(JSON.stringify({ type: "auth", token }));
      };

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data as string) as NewMessagePayload;
          if (data.type === "new_message") {
            onNewMessageRef.current(data.conversation_id);
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        if (stopped) return;
        const delay =
          RECONNECT_DELAY_MS[Math.min(reconnectAttempt, RECONNECT_DELAY_MS.length - 1)];
        reconnectAttempt += 1;
        reconnectTimer = setTimeout(connect, delay);
      };

      ws.onerror = () => {
        ws?.close();
      };
    }

    connect();

    return () => {
      stopped = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      ws?.close();
    };
  }, []);
}
