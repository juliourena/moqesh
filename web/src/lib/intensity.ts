// Intensidad adaptativa derivada del score de la sesión — MISMOS umbrales que el backend
// (moqesh/detection.py intensity_for). 0 = sitio real finito (sigilo); 1..3 = cebo + tarpit.

export function intensityFromScore(score: number): number {
  if (score >= 0.8) return 3;
  if (score >= 0.6) return 2;
  if (score >= 0.4) return 1;
  return 0;
}

export const INTENSITY_LABELS = ['Pasivo', 'Vigilado', 'Cebo', 'Tarpit'] as const;

export const INTENSITY_HINTS = [
  'Sitio real finito — máximo sigilo',
  'Sospecha leve — vocabulario coherente',
  'Cebo denso coherente — más que leer',
  'Tarpit — retardo creciente que quema tokens',
] as const;

export function intensityBadge(level: number): string {
  switch (level) {
    case 3:
      return 'bg-red/20 text-red border-red/30';
    case 2:
      return 'bg-amber/20 text-amber border-amber/30';
    case 1:
      return 'bg-blue/20 text-blue border-blue/30';
    default:
      return 'bg-surface-alt text-fg-muted border-border';
  }
}
