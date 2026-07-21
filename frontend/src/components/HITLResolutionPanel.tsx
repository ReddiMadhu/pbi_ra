import { useEffect, useState } from 'react';
import { X, Check, Ban, ArrowRightLeft, Sparkles, History } from 'lucide-react';
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
  confidence_rationale?: string;
  model_used?: string;
  mapping_type?: string;
  report_kpi_definition?: string;
  alternative_candidates?: { kpi_id: string; name: string; score: number }[];
  warnings?: { type: string; severity: string; message: string }[];
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
  currentUser?: string;
}

export function HITLResolutionPanel({ mapping, canonicalKpis, onClose, onResolved, currentUser = 'analyst' }: HITLResolutionPanelProps) {
  const [analystId, setAnalystId] = useState<string>(() => {
    return localStorage.getItem('governance_analyst_id') || currentUser;
  });
  const [reassignId, setReassignId] = useState('');
  const [promoteName, setPromoteName] = useState('');
  const [promoteDef, setPromoteDef] = useState('');
  const [promoteLob, setPromoteLob] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPromote, setShowPromote] = useState(false);
  const [auditLog, setAuditLog] = useState<any[]>([]);
  const [showAudit, setShowAudit] = useState(false);

  const handleAnalystIdChange = (val: string) => {
    setAnalystId(val);
    localStorage.setItem('governance_analyst_id', val);
  };

  useEffect(() => {
    if (mapping) {
      setPromoteName(mapping.report_kpi_name);
      setPromoteDef(mapping.report_kpi_definition || '');
      setReassignId('');
      setShowPromote(mapping.mapping_status === 'not_found');
      
      fetch(`${API_BASE_URL}/api/v1/governance/mappings/${mapping.mapping_id}/audit-log`)
        .then((r) => r.json())
        .then((data) => {
          if (Array.isArray(data)) setAuditLog(data);
        })
        .catch(() => setAuditLog([]));
    }
  }, [mapping]);

  if (!mapping) return null;

  const act = async (action: string, extra: Record<string, string> = {}) => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/ontology/mappings/${mapping.mapping_id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, analyst_id: analystId || 'analyst', ...extra }),
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
        body: JSON.stringify({
          name: promoteName,
          definition: promoteDef || promoteName,
          line_of_business: promoteLob || undefined,
          analyst_id: analystId || 'analyst',
        }),
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

  // Helper for mapping type styling
  const mappingTypeStyles: Record<string, string> = {
    exact: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
    alias: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
    formula_equivalent: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
    semantic_match: 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20',
    no_match: 'bg-rose-500/10 text-rose-500 border-rose-500/20',
  };

  const formatMappingType = (t: string) => {
    return t.replace('_', ' ').replace(/\b\w/g, (c) => c.toUpperCase());
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative w-full max-w-md bg-background border-l border-border shadow-xl p-6 overflow-y-auto animate-in slide-in-from-right duration-300">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-lg font-bold">Resolve KPI Mapping</h3>
            <div className="flex items-center gap-1.5 mt-1">
              <span className="text-[10px] text-muted-foreground uppercase font-semibold">Reviewer:</span>
              <input
                type="text"
                className="text-xs px-2 py-0.5 rounded border border-border bg-muted/40 font-mono text-foreground focus:outline-none focus:border-primary"
                value={analystId}
                onChange={(e) => handleAnalystIdChange(e.target.value)}
                placeholder="analyst_id"
              />
            </div>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="w-5 h-5" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <div className="flex items-center gap-2 mb-1">
              <p className="text-xs text-muted-foreground uppercase tracking-wider">Report KPI</p>
              {mapping.mapping_type && (
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${mappingTypeStyles[mapping.mapping_type] || 'bg-muted text-muted-foreground'}`}>
                  {formatMappingType(mapping.mapping_type)}
                </span>
              )}
            </div>
            <p className="font-semibold text-lg">{mapping.report_kpi_name}</p>
            {mapping.report_kpi_definition && (
              <p className="text-xs text-muted-foreground mt-1 bg-muted/30 p-2 rounded border border-border/50 font-mono">
                {mapping.report_kpi_definition}
              </p>
            )}
          </div>
          {mapping.report_kpi_lineage?.length > 0 && (
            <div>
              <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Lineage</p>
              <p className="text-sm font-mono text-muted-foreground">{mapping.report_kpi_lineage.join(' → ')}</p>
            </div>
          )}
          <div>
            <p className="text-xs text-muted-foreground uppercase tracking-wider mb-1">Confidence</p>
            <p className="text-sm font-medium">
              {Math.round((mapping.confidence_score || 0) * 100)}% — <span className="capitalize">{mapping.mapping_status.replace('_', ' ')}</span>
            </p>
            {mapping.model_used && (
              <p className="text-[10px] text-muted-foreground mt-0.5">
                Model: <span className="font-mono bg-muted px-1 rounded">{mapping.model_used}</span>
              </p>
            )}
          </div>
          {(mapping.similarity_rationale || mapping.confidence_rationale) && (
            <div className="p-3 rounded-lg bg-muted/50 text-sm text-muted-foreground space-y-1">
              {mapping.similarity_rationale && <p>{mapping.similarity_rationale}</p>}
              {mapping.confidence_rationale && (
                <p className="text-xs border-t border-border/40 pt-1 text-muted-foreground/80 font-mono">
                  Confidence Rationale: {mapping.confidence_rationale}
                </p>
              )}
            </div>
          )}

          {/* Audit History Accordion */}
          {auditLog.length > 0 && (
            <div className="border border-border/60 rounded-lg overflow-hidden text-xs">
              <button
                type="button"
                onClick={() => setShowAudit(!showAudit)}
                className="w-full px-3 py-2 bg-muted/40 hover:bg-muted/60 flex items-center justify-between font-semibold text-muted-foreground transition-colors"
              >
                <span className="flex items-center gap-1.5">
                  <History className="w-3.5 h-3.5 text-sky-400" />
                  Override Audit Trail ({auditLog.length})
                </span>
                <span className="text-[10px]">{showAudit ? 'Hide' : 'Show'}</span>
              </button>
              {showAudit && (
                <div className="p-2 space-y-1.5 max-h-40 overflow-y-auto divide-y divide-border/40 bg-background">
                  {auditLog.map((log) => (
                    <div key={log.id} className="pt-1.5 first:pt-0 space-y-0.5">
                      <div className="flex items-center justify-between text-[10px]">
                        <span className="font-mono text-primary">{log.field_changed}</span>
                        <span className="text-muted-foreground">{log.timestamp ? log.timestamp.slice(0, 16).replace('T', ' ') : ''}</span>
                      </div>
                      <p className="text-muted-foreground text-[11px]">
                        <span className="line-through opacity-70">{log.original_value || 'None'}</span> → <span className="font-medium text-foreground">{log.new_value}</span>
                      </p>
                      <p className="text-[10px] italic text-muted-foreground">Reason: {log.reason} ({log.approval_user})</p>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {mapping.mapping_status === 'not_found' && showPromote ? (
            <div className="space-y-3 border-t border-border pt-4">
              <p className="text-sm font-semibold flex items-center gap-2"><Sparkles className="w-4 h-4 text-amber-500" /> Promote to New KPI</p>
              <input
                className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background"
                value={promoteName}
                onChange={(e) => setPromoteName(e.target.value)}
                placeholder="Canonical KPI name"
              />
              <input
                className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background"
                value={promoteLob}
                onChange={(e) => setPromoteLob(e.target.value)}
                placeholder="Line of Business (optional)"
              />
              <textarea
                className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background min-h-[80px]"
                value={promoteDef}
                onChange={(e) => setPromoteDef(e.target.value)}
                placeholder="Definition"
              />
              <Button onClick={promote} disabled={loading || !promoteName} className="w-full">
                Promote to KPI Ontology
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

              {/* Suggestions Section */}
              {mapping.alternative_candidates && mapping.alternative_candidates.length > 0 && (
                <div className="mt-2 space-y-2">
                  <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Top Match Suggestions</p>
                  <div className="flex flex-col gap-1.5">
                    {mapping.alternative_candidates.map((cand) => (
                      <button
                        key={cand.kpi_id}
                        type="button"
                        onClick={() => setReassignId(cand.kpi_id)}
                        className={`w-full text-left px-3 py-2 text-xs rounded-lg border transition-all flex items-center justify-between
                          ${reassignId === cand.kpi_id
                            ? 'border-primary bg-primary/10 text-primary font-medium'
                            : 'border-border bg-card hover:bg-muted text-foreground'
                          }`}
                      >
                        <span className="truncate pr-2">{cand.name}</span>
                        <span className="shrink-0 font-mono text-[10px] text-muted-foreground">
                          {Math.round(cand.score * 100)}%
                        </span>
                      </button>
                    ))}
                  </div>
                </div>
              )}

              <div className="flex gap-2 mt-2">
                <select
                  className="flex-1 px-3 py-2 text-sm rounded-lg border border-border bg-background"
                  value={reassignId}
                  onChange={(e) => setReassignId(e.target.value)}
                >
                  <option value="">Choose alternative…</option>
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
