import { useEffect, useState, useMemo } from 'react';
import { ShieldAlert, CheckCircle, Save, Loader2, RefreshCw, Layers } from 'lucide-react';
import { API_BASE_URL } from '@/config';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface PendingDashboard {
  id: number;
  name: string;
  workbook_name: string | null;
  ontology_sector: string | null;
  ontology_subdomain: string | null;
  line_of_business: string | null;
  scope_status: string;
}

const SECTOR_SUBDOMAINS: Record<string, string[]> = {
  insurance: [
    'marketing',
    'distribution',
    'actuarial_and_risk',
    'underwriting',
    'claims_litigation',
    'service_and_operations',
    'cx_and_digital',
  ],
  banking: ['retail', 'corporate', 'risk', 'shared'],
  finance: ['accounting', 'treasury', 'fp_and_a', 'shared'],
  operational: ['supply_chain', 'hr', 'it_ops', 'shared'],
};

const SUBDOMAIN_LABELS: Record<string, string> = {
  marketing: 'Marketing',
  distribution: 'Distribution',
  actuarial_and_risk: 'Actuarial & Risk',
  underwriting: 'Underwriting',
  claims_litigation: 'Claims & Litigation',
  service_and_operations: 'Service & Operations',
  cx_and_digital: 'CX & Digital',
  retail: 'Retail',
  corporate: 'Corporate',
  risk: 'Risk',
  shared: 'Shared',
  accounting: 'Accounting',
  treasury: 'Treasury',
  fp_and_a: 'FP&A',
  supply_chain: 'Supply Chain',
  hr: 'HR',
  it_ops: 'IT Ops',
};

const SECTOR_LABELS: Record<string, string> = {
  insurance: 'Insurance',
  banking: 'Banking',
  finance: 'Finance & Accounting',
  operational: 'Operations / HR / IT',
};

export function ScopeApprovalView({ onNavigate }: { onNavigate?: (view: any) => void }) {
  const [dashboards, setDashboards] = useState<PendingDashboard[]>([]);
  const [loading, setLoading] = useState(true);
  const [approvingIds, setApprovingIds] = useState<Record<number, boolean>>({});
  const [editedScopes, setEditedScopes] = useState<Record<number, { sector: string; subdomain: string; lob: string }>>({});

  const loadPendingDashboards = async () => {
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/ontology/dashboards/pending-scope`);
      const data = await res.json();
      if (Array.isArray(data)) {
        setDashboards(data);
        const scopes: Record<number, { sector: string; subdomain: string; lob: string }> = {};
        data.forEach((d) => {
          scopes[d.id] = {
            sector: d.ontology_sector || 'insurance',
            subdomain: d.ontology_subdomain || 'service_and_operations',
            lob: d.line_of_business || '',
          };
        });
        setEditedScopes(scopes);
      }
    } catch (err) {
      console.error('Failed to load pending dashboards', err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadPendingDashboards();
  }, []);

  const handleScopeChange = (id: number, key: 'sector' | 'subdomain' | 'lob', value: string) => {
    setEditedScopes((prev) => {
      const current = { ...prev[id] };
      current[key] = value;
      if (key === 'sector') {
        // Reset subdomain to the first allowed for the new sector
        current.subdomain = SECTOR_SUBDOMAINS[value]?.[0] || 'shared';
      }
      return {
        ...prev,
        [id]: current,
      };
    });
  };

  const approveScope = async (id: number) => {
    const scope = editedScopes[id];
    if (!scope) return;
    setApprovingIds((prev) => ({ ...prev, [id]: true }));
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/ontology/dashboards/${id}/approve-scope`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          sector: scope.sector,
          subdomain: scope.subdomain,
          line_of_business: scope.lob || null,
        }),
      });
      if (!res.ok) throw new Error('Approval failed');
      
      // Remove approved dashboard from list
      setDashboards((prev) => prev.filter((d) => d.id !== id));
    } catch (err) {
      alert('Failed to approve dashboard classification scope.');
    } finally {
      setApprovingIds((prev) => ({ ...prev, [id]: false }));
    }
  };

  const approveAll = async () => {
    if (dashboards.length === 0) return;
    if (!confirm(`Are you sure you want to approve all ${dashboards.length} pending dashboard classifications?`)) return;
    
    setLoading(true);
    for (const d of dashboards) {
      const scope = editedScopes[d.id];
      if (!scope) continue;
      try {
        await fetch(`${API_BASE_URL}/api/v1/ontology/dashboards/${d.id}/approve-scope`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sector: scope.sector,
            subdomain: scope.subdomain,
            line_of_business: scope.lob || null,
          }),
        });
      } catch (err) {
        console.error(`Failed to approve dashboard ${d.id}`, err);
      }
    }
    loadPendingDashboards();
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Layers className="w-6 h-6 text-indigo-500" />
            Dashboard Scope Classification Review (HITL)
          </h2>
          <p className="text-sm text-slate-500 mt-1">
            Review and approve the Sector, Line of Business (LOB), and Business Function (Subdomain) classifications before running the KPI ontology mapping.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={loadPendingDashboards} disabled={loading} className="gap-1">
            <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
          </Button>
          {dashboards.length > 0 && (
            <Button variant="default" size="sm" onClick={approveAll} disabled={loading} className="bg-indigo-600 hover:bg-indigo-700">
              <CheckCircle className="w-3.5 h-3.5 mr-1" /> Approve All ({dashboards.length})
            </Button>
          )}
        </div>
      </div>

      {loading && dashboards.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-24 text-slate-500 gap-2">
          <Loader2 className="w-8 h-8 animate-spin text-indigo-500" />
          <p className="text-sm font-medium">Loading pending classifications...</p>
        </div>
      ) : dashboards.length === 0 ? (
        <Card className="border-dashed border-2 border-border/80">
          <CardContent className="flex flex-col items-center justify-center py-16 text-center space-y-4">
            <div className="w-12 h-12 rounded-full bg-emerald-500/10 flex items-center justify-center">
              <CheckCircle className="w-6 h-6 text-emerald-500" />
            </div>
            <div>
              <p className="font-semibold text-foreground text-lg">All Dashboards Approved</p>
              <p className="text-xs text-muted-foreground max-w-sm mt-1 mx-auto leading-relaxed">
                There are no dashboards pending taxonomy review. All KPIs have been submitted to the ontology mapping pipeline in the background.
              </p>
            </div>
            {onNavigate && (
              <div className="flex gap-3 pt-2">
                <Button variant="outline" size="sm" onClick={() => onNavigate('overview')} className="border-indigo-500/20 text-indigo-400 hover:bg-indigo-500/10 hover:text-indigo-300">
                  Go to Dashboard Overview
                </Button>
                <Button variant="default" size="sm" onClick={() => onNavigate('kpi_governance')} className="bg-indigo-600 hover:bg-indigo-700">
                  Go to KPI Ontology Mapping
                </Button>
              </div>
            )}
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4">
          {dashboards.map((d) => {
            const scope = editedScopes[d.id] || { sector: 'insurance', subdomain: 'service_and_operations', lob: '' };
            const isApproving = approvingIds[d.id] || false;
            return (
              <Card key={d.id} className="border border-border bg-card shadow-sm hover:border-indigo-500/20 transition-all duration-200">
                <CardHeader className="pb-3 border-b border-border/50">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <span className="text-[10px] uppercase font-bold text-indigo-500 tracking-wider">
                        Workbook: {d.workbook_name || 'unknown'}
                      </span>
                      <CardTitle className="text-base mt-0.5">{d.name}</CardTitle>
                    </div>
                    <Badge className="bg-amber-500/10 text-amber-500 border border-amber-500/20 text-[10px] hover:bg-amber-500/10">
                      Pending Scope Approval
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent className="p-5">
                  <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                    {/* Sector Selection */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-muted-foreground uppercase">Sector</label>
                      <select
                        className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:border-indigo-500"
                        value={scope.sector}
                        onChange={(e) => handleScopeChange(d.id, 'sector', e.target.value)}
                      >
                        {Object.keys(SECTOR_SUBDOMAINS).map((sec) => (
                          <option key={sec} value={sec}>
                            {SECTOR_LABELS[sec]}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* Subdomain / Business Function */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-muted-foreground uppercase">Business Function / Subdomain</label>
                      <select
                        className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:border-indigo-500"
                        value={scope.subdomain}
                        onChange={(e) => handleScopeChange(d.id, 'subdomain', e.target.value)}
                      >
                        {(SECTOR_SUBDOMAINS[scope.sector] || []).map((sub) => (
                          <option key={sub} value={sub}>
                            {SUBDOMAIN_LABELS[sub] || sub}
                          </option>
                        ))}
                      </select>
                    </div>

                    {/* LOB input */}
                    <div className="space-y-1.5">
                      <label className="text-xs font-semibold text-muted-foreground uppercase">Line of Business (LOB)</label>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          className="flex-1 px-3 py-2 rounded-lg border border-border bg-background text-sm focus:outline-none focus:border-indigo-500"
                          placeholder="e.g. Personal Lines, Commercial, Retail"
                          value={scope.lob}
                          onChange={(e) => handleScopeChange(d.id, 'lob', e.target.value)}
                        />
                        <Button
                          onClick={() => approveScope(d.id)}
                          disabled={isApproving}
                          className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1 text-xs shrink-0"
                        >
                          {isApproving ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : (
                            <Save className="w-3.5 h-3.5" />
                          )}
                          Approve
                        </Button>
                      </div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Badge({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium ${className}`}>
      {children}
    </span>
  );
}
