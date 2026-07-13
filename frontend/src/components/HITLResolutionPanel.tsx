import { useEffect, useState } from 'react';
import { X, Check, Ban, ArrowRightLeft, Sparkles } from 'lucide-react';
import { API_BASE_URL } from '@/config';
import { Button } from './ui/button';

export interface MappingRow {
  mapping_id: string;
  report_id: string;
  report_kpi_name: string;
  report_kpi_lineage: string[];
  canonical_kpi_id: string | null;
  similarity_score: number;
  confidence_score: number;
  similarity_rationale: string;
  mapping_status: string;
}

interface CanonicalKPI {
  kpi_id: string;
  name: string;
}

interface HITLResolutionPanelProps {
  mapping: MappingRow | null;
  canonicalKpis: CanonicalKPI[];
  onClose: () => void;
  onResolved: () => void;
}

export function HITLResolutionPanel({ mapping, canonicalKpis, onClose, onResolved }: HITLResolutionPanelProps) {
  const [reassignId, setReassignId] = useState('');
  const [promoteName, setPromoteName] = useState('');
  const [promoteDef, setPromoteDef] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPromote, setShowPromote] = useState(false);

  useEffect(() => {
    if (mapping) {
      setPromoteName(mapping.report_kpi_name);
      setPromoteDef('');
      setShowPromote(mapping.mapping_status === 'not_found');
    }
  }, [mapping]);

  if (!mapping) return null;

  const act = async (action: string, extra: Record<string, string> = {}) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/ontology/mappings/${mapping.mapping_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, analyst_id: 'analyst', ...extra }),
      });
      if (!res.ok) throw new Error('Action failed');
      onResolved();
      onClose();
    } catch {
      alert('Failed to update mapping');
    } finally {
      setLoading(false);
    }
  };

  const promote = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/ontology/mappings/${mapping.mapping_id}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: promoteName, definition: promoteDef || promoteName, analyst_id: 'analyst' }),
      });
      if (!res.ok) throw new Error('Promote failed');
      onResolved();
      onClose();
    } catch {
      alert('Failed to promote KPI');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-md bg-background border-l border-border shadow-xl p-6 overflow-y-auto animate-in slide-in-from-right duration-300">
        <div className="flex items-center justify-between mb-6">
          <h3 className="text-lg font-bold">Resolve KPI Mapping</h3>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Report KPI</p>
            <p className="font-semibold">{mapping.report_kpi_name}</p>
          </div>
          {mapping.report_kpi_lineage?.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Lineage</p>
              <p className="text-sm font-mono text-muted-foreground">{mapping.report_kpi_lineage.join(' → ')}</p>
            </div>
          )}
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Confidence</p>
            <p className="text-sm">{Math.round((mapping.confidence_score || 0) * 100)}% — {mapping.mapping_status}</p>
          </div>
          {mapping.similarity_rationale && (
            <div className="p-3 rounded-lg bg-muted/50 text-sm text-muted-foreground">{mapping.similarity_rationale}</div>
          )}

          {mapping.mapping_status === 'not_found' && showPromote ? (
            <div className="space-y-3 border-t border-border pt-4">
              <p className="text-sm font-semibold flex items-center gap-2"><Sparkles className="w-4 h-4" /> Promote to New KPI</p>
              <input
                className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background"
                value={promoteName}
                onChange={(e) => setPromoteName(e.target.value)}
                placeholder="Canonical name"
              />
              <textarea
                className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background min-h-[80px]"
                value={promoteDef}
                onChange={(e) => setPromoteDef(e.target.value)}
                placeholder="Definition"
              />
              <Button onClick={promote} disabled={loading || !promoteName} className="w-full">
                Promote to Ontology Bank
              </Button>
            </div>
          ) : (
            <div className="flex flex-col gap-2 border-t border-border pt-4">
              <Button variant="outline" onClick={() => act('accept')} disabled={loading} className="justify-start gap-2">
                <Check className="w-4 h-4 text-emerald-500" /> Accept mapping
              </Button>
              <Button variant="outline" onClick={() => act('reject')} disabled={loading} className="justify-start gap-2">
                <Ban className="w-4 h-4 text-red-500" /> Reject mapping
              </Button>
              <div className="flex gap-2">
                <select
                  className="flex-1 px-3 py-2 text-sm rounded-lg border border-border bg-background"
                  value={reassignId}
                  onChange={(e) => setReassignId(e.target.value)}
                >
                  <option value="">Reassign to…</option>
                  {canonicalKpis.map((k) => (
                    <option key={k.kpi_id} value={k.kpi_id}>{k.name}</option>
                  ))}
                </select>
                <Button
                  variant="outline"
                  disabled={loading || !reassignId}
                  onClick={() => act('reassign', { canonical_kpi_id: reassignId })}
                >
                  <ArrowRightLeft className="w-4 h-4" />
                </Button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
