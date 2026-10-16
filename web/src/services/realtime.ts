// Cliente de tiempo real con WebSocket NATIVO (reemplazo de SignalR).
// Se conecta a /hubs/stream (proxyeado a la API en dev, mismo origen en prod)
// y reconecta solo si la conexión se cae.

export interface LiveEvent {
  event: string;
  data: Record<string, unknown>;
}

export function connectLive(onEvent: (e: LiveEvent) => void): () => void {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const url = `${proto}://${location.host}/hubs/stream`;
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: ReturnType<typeof setTimeout> | undefined;

  const open = () => {
    ws = new WebSocket(url);
    ws.onmessage = (m) => {
      try {
        onEvent(JSON.parse(m.data) as LiveEvent);
      } catch {
        /* mensaje no-JSON: ignorar */
      }
    };
    ws.onclose = () => {
      if (!closed) retry = setTimeout(open, 3000);
    };
    ws.onerror = () => ws?.close();
  };

  open();

  return () => {
    closed = true;
    if (retry) clearTimeout(retry);
    ws?.close();
  };
}
