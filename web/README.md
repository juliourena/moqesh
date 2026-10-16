# Dashboard de Moqesh AI (web)

Frontend del dashboard: React + TypeScript + Vite + Tailwind. Consume la API en
`/api`, el tiempo real por WebSocket en `/hubs/stream` y las descargas en `/download`.

## Desarrollo

```bash
npm install
npm run dev     # http://localhost:5173 (proxy /api, /hubs y /download → :5000)
```

Arranca también el backend (`moqesh` en el repo raíz) para tener datos reales.

## Build

```bash
npm run build   # type-check (tsc) + build de producción a web/dist
```

En producción el backend sirve `web/dist` como SPA (mismo origen que la API). En la
imagen Docker el build se hace en una etapa de Node y se copia al servidor Python.

## Estructura

- `src/pages/` — Dashboard, Sesiones, Requests, Alertas, Reglas, Escenarios, Blocks, **Sensores**.
- `src/services/api.ts` — cliente REST tipado. `src/services/realtime.ts` — WebSocket nativo.
- `src/types/index.ts` — tipos del contrato (camelCase, espejo de `moqesh/schemas.py`).
