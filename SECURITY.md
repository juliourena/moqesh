# Política de seguridad

Moqesh AI es una herramienta **defensiva** (honeypot/deception). Agradecemos la
divulgación responsable de vulnerabilidades.

## Reportar una vulnerabilidad

- **No** abras un issue público.
- Usa los **GitHub Security Advisories** privados del repositorio
  (pestaña *Security → Report a vulnerability*).
- Incluye versión/commit, pasos de reproducción y el impacto. Respondemos lo antes posible
  y coordinamos la divulgación tras un arreglo.

## Modelo de amenaza y decisiones de diseño

Moqesh se despliega, por definición, en entornos hostiles. Supuestos clave:

- El **honeypot es atacado a propósito**. El contenido-cebo (claves AWS/JWT/DB,
  binarios señuelo) es **inerte**: no corresponde a credenciales reales ni ejecuta nada.
- Los **sensores remotos** pueden vivir en servidores que sean comprometidos. Por eso su
  clave es **de mínimo privilegio** (solo ingestión + control de su propio sensor),
  **revocable/rotable** en un clic, y la ingestión se trata siempre como **hostil**
  (validación, rate-limit, dedup, filtrado por prefijo).
- El canal sensor↔servidor usa **HMAC firmado en ambos sentidos** (incluidas las
  respuestas de control) + ventana anti-replay, para que un MITM no pueda forjar envíos
  ni órdenes de apagado. Despliega el servidor tras **TLS**.
- El modo agentless envía **solo las líneas del cebo** (filtro por prefijo) para no
  exfiltrar tráfico real de usuarios; usa el **dry-run** antes de activar.

## Uso responsable

Despliega sensores únicamente en infraestructura que **estás autorizado** a proteger.
Aísla la ruta del cebo de las rutas reales y aplica la config de servido seguro incluida
en cada bundle (sirve el contenido como datos, nunca como código).
