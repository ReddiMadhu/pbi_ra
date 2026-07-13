import { Brain, CheckCircle2, AlertTriangle, XCircle } from 'lucide-react';

export interface OntologyKPIInventory {
  report_id: string;
  total: number;
  mapped: number;
  ambiguous: number;
  not_found: number;
  ontology_score: number;
}

interface OntologyScoreBadgeProps {
  inventory?: OntologyKPIInventory | null;
  compact?: boolean;
}

export function OntologyScoreBadge({ inventory, compact = false }: OntologyScoreBadgeProps) {
  if (!inventory || inventory.total === 0) {
    return (
      <div className="text-xs text-muted-foreground italic flex items-center gap-1.5 mt-2">
        <Brain className="w-3.5 h-3.5" />
        KPI mapping pending
      </div>
    );
  }

  const pct = Math.round((inventory.ontology_score || 0) * 100);

  if (compact) {
    return (
      <div className="flex items-center gap-2 text-xs text-muted-foreground mt-2">
        <Brain className="w-3.5 h-3.5 text-primary" />
        <span>{pct}% KPI overlap</span>
        <span className="text-muted-foreground/50">·</span>
        <span>{inventory.mapped} mapped</span>
      </div>
    );
  }

  return (
    <div className="mt-3 p-3 rounded-lg border border-border bg-muted/30">
      <div className="flex items-center gap-2 mb-2">
        <Brain className="w-4 h-4 text-primary" />
        <span className="text-xs font-semibold uppercase tracking-wider text-primary">Ontology KPI Inventory</span>
        <span className="ml-auto text-xs font-bold">{pct}% mapped</span>
      </div>
      <div className="grid grid-cols-3 gap-2 text-center text-xs mb-2">
        <div className="flex flex-col items-center gap-0.5">
          <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" />
          <span className="font-bold">{inventory.mapped}</span>
          <span className="text-muted-foreground">Mapped</span>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />
          <span className="font-bold">{inventory.ambiguous}</span>
          <span className="text-muted-foreground">Review</span>
        </div>
        <div className="flex flex-col items-center gap-0.5">
          <XCircle className="w-3.5 h-3.5 text-red-500" />
          <span className="font-bold">{inventory.not_found}</span>
          <span className="text-muted-foreground">Not Found</span>
        </div>
      </div>
      <div className="h-1.5 rounded-full bg-muted overflow-hidden">
        <div className="h-full bg-primary rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
