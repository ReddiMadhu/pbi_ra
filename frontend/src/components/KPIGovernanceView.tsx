import { useEffect, useState, useMemo, useCallback } from 'react';
import {
  BookOpen, Search, Loader2, Filter, CheckCircle2, XCircle,
  AlertTriangle, ChevronDown, ChevronRight, Check, Ban,
  ArrowRightLeft, Sparkles, History, Save, Plus, BarChart2,
  Eye, Edit3, MessageSquare, RefreshCw
} from 'lucide-react';
import { API_BASE_URL } from '@/config';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

/* ── Types ──────────────────────────────────────────────── */
interface MappingItem {
  mapping_id: string;
  report_kpi_name: string;
  report_kpi_definition?: string;
  report_kpi_lineage?: string[];
  report_kpi_aggregation?: string;
  worksheet_name?: string;
  canonical_kpi?: {
    kpi_id: string;
    name: string;
    definition?: string;
    domain?: string;
    sector?: string;
    subdomain?: string;
    aggregation_type?: string;
  } | null;
  similarity_score?: number;
  confidence_score?: number;
  similarity_rationale?: string;
  confidence_rationale?: string;
  mapping_status: string;
  resolved_by?: string;
  mapping_type?: string;
  alternative_candidates?: { kpi_id: string; name: string; score: number }[];
  model_used?: string;
  // UI augmented
  dashboardName?: string;
  dashboardId?: number;
  workbookName?: string;
}

interface AuditEntry {
  id: number;
  mapping_id: string;
  field_changed: string;
  original_value?: string;
  new_value?: string;
  reason?: string;
  approval_user?: string;
  timestamp?: string;
}

interface CanonicalKPI {
  kpi_id: string;
  name: string;
  definition?: string;
  sector?: string;
  subdomain?: string;
}

interface PendingChange {
  action: 'accept' | 'reject' | 'reassign';
  canonical_kpi_id?: string;
  justification: string;
}

/* ── Helpers ────────────────────────────────────────────── */
function confidenceBadge(score: number | undefined) {
  if (score == null) return <span className="text-muted-foreground/40">—</span>;
  if (score >= 0.80) return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/20 text-[10px]">High</Badge>;
  if (score >= 0.50) return <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/20 text-[10px]">Medium</Badge>;
  return <Badge className="bg-red-500/15 text-red-400 border-red-500/20 text-[10px]">Low</Badge>;
}

function similarityBar(score: number | undefined) {
  if (score == null) return <span className="text-muted-foreground/40">—</span>;
  const pct = Math.round(score * 100);
  const color = score >= 0.80 ? 'bg-emerald-500' : score >= 0.50 ? 'bg-amber-500' : 'bg-red-500';
  const textColor = score >= 0.80 ? 'text-emerald-400' : score >= 0.50 ? 'text-amber-400' : 'text-red-400';
  const label = score >= 0.80 ? 'High' : score >= 0.50 ? 'Medium' : 'Low';
  return (
    <div className="flex items-center gap-2 min-w-[100px]">
      <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className={`text-[10px] font-bold ${textColor} whitespace-nowrap`}>{label}</span>
    </div>
  );
}

function statusBadge(status: string) {
  const s = status || '';
  if (['auto_accepted', 'human_accepted', 'promoted'].includes(s)) {
    return <Badge className="bg-emerald-500/15 text-emerald-400 border-emerald-500/20 text-[10px] gap-1"><CheckCircle2 className="w-3 h-3" />Mapped</Badge>;
  }
  if (s === 'pending_review') {
    return <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/20 text-[10px] gap-1"><AlertTriangle className="w-3 h-3" />Review</Badge>;
  }
  if (s === 'not_found') {
    return <Badge className="bg-red-500/15 text-red-400 border-red-500/20 text-[10px] gap-1"><XCircle className="w-3 h-3" />Not Found</Badge>;
  }
  if (s === 'human_rejected') {
    return <Badge className="bg-rose-500/15 text-rose-400 border-rose-500/20 text-[10px] gap-1"><Ban className="w-3 h-3" />Rejected</Badge>;
  }
  return <Badge variant="outline" className="text-[10px]">{s || '—'}</Badge>;
}

const mappingTypeStyles: Record<string, string> = {
  exact: 'bg-emerald-500/10 text-emerald-500 border-emerald-500/20',
  alias: 'bg-blue-500/10 text-blue-500 border-blue-500/20',
  formula_equivalent: 'bg-purple-500/10 text-purple-500 border-purple-500/20',
  semantic_match: 'bg-indigo-500/10 text-indigo-500 border-indigo-500/20',
  no_match: 'bg-rose-500/10 text-rose-500 border-rose-500/20',
};

/* ── Main Component ─────────────────────────────────────── */
export function KPIGovernanceView({ workbooksData, onNavigate }: { workbooksData: any[]; onNavigate?: (view: any) => void }) {
  // ── Data State ───────
  const [allMappings, setAllMappings] = useState<MappingItem[]>([]);
  const [canonicalKpis, setCanonicalKpis] = useState<CanonicalKPI[]>([]);
  const [loading, setLoading] = useState(true);
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [auditLogs, setAuditLogs] = useState<Record<string, AuditEntry[]>>({});
  const [showAuditFor, setShowAuditFor] = useState<string | null>(null);

  // ── Filter State ─────
  const [search, setSearch] = useState('');
  const [filterStatus, setFilterStatus] = useState('all');
  const [filterConfidence, setFilterConfidence] = useState('all');
  const [filterDashboard, setFilterDashboard] = useState('all');
  const [filterWorkbook, setFilterWorkbook] = useState('all');

  // ── Inline Review State ─────
  const [pendingChanges, setPendingChanges] = useState<Record<string, PendingChange>>({});
  const [activeReview, setActiveReview] = useState<string | null>(null);
  const [reviewJustification, setReviewJustification] = useState('');
  const [reassignKpiId, setReassignKpiId] = useState('');
  const [saving, setSaving] = useState(false);

  // ── New KPI Inline State ─────
  const [showNewKpi, setShowNewKpi] = useState<string | null>(null);
  const [newKpiForm, setNewKpiForm] = useState({ name: '', definition: '', lob: '', sector: '', subdomain: '' });

  // ── Reviewer State ─────
  const [analystId] = useState(() => localStorage.getItem('governance_analyst_id') || 'analyst_lead');

  /* ── Data Loading ────────────────────────────────────── */
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const workbookNames = new Set<string>();
      (workbooksData || []).forEach(wb => {
        const name = wb.source_file?.split(/[/\\]/).pop() || wb.source_file;
        if (name) workbookNames.add(name);
      });

      const [kpisRes, ...wbResults] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/ontology/kpis?limit=5000&status=active`),
        ...Array.from(workbookNames).map(name =>
          fetch(`${API_BASE_URL}/api/v1/ontology/workbook/${encodeURIComponent(name)}/kpis`)
            .then(r => r.json())
            .then(data => ({ workbookName: name, data }))
            .catch(() => ({ workbookName: name, data: { dashboards: [] } }))
        ),
      ]);

      const kpiData = await kpisRes.json();
      setCanonicalKpis(Array.isArray(kpiData) ? kpiData : []);

      // Flatten all mappings across workbooks/dashboards
      const mappings: MappingItem[] = [];
      wbResults.forEach((result: any) => {
        (result.data?.dashboards || []).forEach((dash: any) => {
          (dash.items || []).forEach((item: any) => {
            mappings.push({
              ...item,
              dashboardName: dash.dashboard_name,
              dashboardId: dash.dashboard_id,
              workbookName: result.workbookName,
            });
          });
        });
      });
      setAllMappings(mappings);
    } catch {
      setAllMappings([]);
      setCanonicalKpis([]);
    } finally {
      setLoading(false);
    }
  }, [workbooksData]);

  useEffect(() => { loadData(); }, [loadData]);

  /* ── Fetch Audit Log ──────────────────────────────────── */
  const fetchAudit = useCallback(async (mappingId: string) => {
    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/governance/mappings/${mappingId}/audit-log`);
      const data = await res.json();
      setAuditLogs(prev => ({ ...prev, [mappingId]: Array.isArray(data) ? data : [] }));
    } catch {
      setAuditLogs(prev => ({ ...prev, [mappingId]: [] }));
    }
  }, []);

  /* ── Computed ──────────────────────────────────────────── */
  const summary = useMemo(() => {
    let total = 0, mapped = 0, review = 0, notFound = 0;
    allMappings.forEach(m => {
      total++;
      const s = m.mapping_status || '';
      if (['auto_accepted', 'human_accepted', 'promoted'].includes(s)) mapped++;
      else if (s === 'pending_review') review++;
      else if (s === 'not_found') notFound++;
    });
    return { total, mapped, review, notFound, score: total > 0 ? mapped / total : 0 };
  }, [allMappings]);

  const dashboardNames = useMemo(() => {
    return ['all', ...new Set(allMappings.map(m => m.dashboardName || '').filter(Boolean))];
  }, [allMappings]);

  const workbookNames = useMemo(() => {
    return ['all', ...new Set(allMappings.map(m => m.workbookName || '').filter(Boolean))];
  }, [allMappings]);

  const filteredMappings = useMemo(() => {
    return allMappings.filter(m => {
      const q = search.toLowerCase();
      if (q && !m.report_kpi_name.toLowerCase().includes(q)
        && !(m.canonical_kpi?.name || '').toLowerCase().includes(q)
        && !(m.worksheet_name || '').toLowerCase().includes(q)) return false;
      if (filterStatus !== 'all') {
        if (filterStatus === 'mapped' && !['auto_accepted', 'human_accepted', 'promoted'].includes(m.mapping_status)) return false;
        if (filterStatus === 'pending_review' && m.mapping_status !== 'pending_review') return false;
        if (filterStatus === 'not_found' && m.mapping_status !== 'not_found') return false;
        if (filterStatus === 'rejected' && m.mapping_status !== 'human_rejected') return false;
      }
      if (filterConfidence !== 'all') {
        const c = m.confidence_score ?? 0;
        if (filterConfidence === 'high' && c < 0.80) return false;
        if (filterConfidence === 'medium' && (c < 0.50 || c >= 0.80)) return false;
        if (filterConfidence === 'low' && c >= 0.50) return false;
      }
      if (filterDashboard !== 'all' && m.dashboardName !== filterDashboard) return false;
      if (filterWorkbook !== 'all' && m.workbookName !== filterWorkbook) return false;
      return true;
    });
  }, [allMappings, search, filterStatus, filterConfidence, filterDashboard, filterWorkbook]);

  /* ── Inline Review Actions ────────────────────────────── */
  const handleInlineAction = (mappingId: string, action: 'accept' | 'reject' | 'reassign') => {
    if (action === 'reassign') {
      setActiveReview(mappingId);
      setReviewJustification('');
      setReassignKpiId('');
    } else {
      setActiveReview(mappingId);
      setReviewJustification('');
      setPendingChanges(prev => ({
        ...prev,
        [mappingId]: { action, justification: '', canonical_kpi_id: undefined },
      }));
    }
  };

  const confirmAction = (mappingId: string, action: 'accept' | 'reject' | 'reassign') => {
    if (!reviewJustification.trim()) return;
    setPendingChanges(prev => ({
      ...prev,
      [mappingId]: {
        action,
        justification: reviewJustification,
        canonical_kpi_id: action === 'reassign' ? reassignKpiId : undefined,
      },
    }));
    setActiveReview(null);
    setReviewJustification('');
    setReassignKpiId('');
  };

  /* ── Save All ──────────────────────────────────────────── */
  const saveAllChanges = async () => {
    const entries = Object.entries(pendingChanges);
    if (entries.length === 0) return;
    setSaving(true);
    try {
      for (const [mappingId, change] of entries) {
        // 1. Write audit entry with justification
        await fetch(`${API_BASE_URL}/api/v1/governance/mappings/${mappingId}/audit-log`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            field_changed: 'mapping_status',
            original_value: allMappings.find(m => m.mapping_id === mappingId)?.mapping_status,
            new_value: change.action === 'accept' ? 'human_accepted' : change.action === 'reject' ? 'human_rejected' : 'human_accepted',
            reason: change.justification,
            approval_user: analystId,
          }),
        });

        // 2. Perform the action
        await fetch(`${API_BASE_URL}/api/v1/ontology/mappings/${mappingId}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            action: change.action,
            analyst_id: analystId,
            ...(change.canonical_kpi_id ? { canonical_kpi_id: change.canonical_kpi_id } : {}),
          }),
        });
      }

      setPendingChanges({});
      await loadData();
    } catch {
      alert('Failed to save some changes. Please try again.');
    } finally {
      setSaving(false);
    }
  };

  /* ── Promote New KPI ──────────────────────────────────── */
  const promoteNewKpi = async (mappingId: string) => {
    if (!newKpiForm.name.trim() || !newKpiForm.definition.trim()) return;
    setSaving(true);
    try {
      await fetch(`${API_BASE_URL}/api/v1/ontology/mappings/${mappingId}/promote`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newKpiForm.name,
          definition: newKpiForm.definition,
          line_of_business: newKpiForm.lob || undefined,
          sector: newKpiForm.sector || undefined,
          subdomain: newKpiForm.subdomain || undefined,
          analyst_id: analystId,
        }),
      });
      setShowNewKpi(null);
      setNewKpiForm({ name: '', definition: '', lob: '', sector: '', subdomain: '' });
      await loadData();
    } catch {
      alert('Failed to create new KPI');
    } finally {
      setSaving(false);
    }
  };

  const changesCount = Object.keys(pendingChanges).length;

  /* ── Render ────────────────────────────────────────────── */
  return (
    <div className="space-y-5 animate-in fade-in duration-300">
      {/* ── Page Header ──────────────────────────────────── */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-primary" />
            KPI Ontology Mapping
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Unified governance workspace — Map, review, approve, and audit all KPI mappings in one place
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {onNavigate && (
            <Button variant="outline" size="sm" onClick={() => onNavigate('kpi_ontology')} className="border-indigo-500/30 text-indigo-400 hover:bg-indigo-500/10">
              <BookOpen className="w-3.5 h-3.5 mr-1.5" />
              KPI Ontology Bank
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={loadData} disabled={loading}>
            <RefreshCw className={`w-3.5 h-3.5 mr-1.5 ${loading ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {changesCount > 0 && (
            <Button size="sm" onClick={saveAllChanges} disabled={saving} className="gap-1.5">
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              Save {changesCount} Change{changesCount !== 1 ? 's' : ''}
            </Button>
          )}
        </div>
      </div>

      {/* ── Context Tags ─────────────────────────────────── */}
      {workbooksData.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {workbooksData.map((wb, i) => (
            <span key={i} className="px-2.5 py-1 rounded-full bg-primary/10 text-primary text-[11px] font-medium border border-primary/20">
              {wb.source_file?.split(/[/\\]/).pop() || wb.source_file}
            </span>
          ))}
        </div>
      )}

      {/* ── Summary Cards ────────────────────────────────── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Card className={`cursor-pointer transition-all ${filterStatus === 'all' ? 'ring-2 ring-primary border-transparent' : 'hover:border-primary/50'}`} onClick={() => setFilterStatus('all')}>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold">{summary.total}</p>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mt-1">Total Mappings</p>
          </CardContent>
        </Card>
        <Card className={`cursor-pointer transition-all ${filterStatus === 'mapped' ? 'ring-2 ring-emerald-500 border-transparent' : 'hover:border-emerald-500/50'}`} onClick={() => setFilterStatus(filterStatus === 'mapped' ? 'all' : 'mapped')}>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-emerald-400">{summary.mapped}</p>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mt-1">Mapped</p>
          </CardContent>
        </Card>
        <Card className={`cursor-pointer transition-all ${filterStatus === 'pending_review' ? 'ring-2 ring-amber-500 border-transparent' : 'hover:border-amber-500/50'}`} onClick={() => setFilterStatus(filterStatus === 'pending_review' ? 'all' : 'pending_review')}>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-amber-400">{summary.review}</p>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mt-1">Pending Review</p>
          </CardContent>
        </Card>
        <Card className={`cursor-pointer transition-all ${filterStatus === 'not_found' ? 'ring-2 ring-red-500 border-transparent' : 'hover:border-red-500/50'}`} onClick={() => setFilterStatus(filterStatus === 'not_found' ? 'all' : 'not_found')}>
          <CardContent className="p-4 text-center">
            <p className="text-2xl font-bold text-red-400">{summary.notFound}</p>
            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mt-1">Not Found</p>
          </CardContent>
        </Card>
      </div>

      {/* ── Filters ──────────────────────────────────────── */}
      <Card>
        <CardContent className="p-4">
          <div className="flex gap-3 flex-wrap items-center">
            <Filter className="w-4 h-4 text-muted-foreground" />
            <div className="relative flex-1 min-w-[200px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <input
                className="w-full pl-10 pr-4 py-2 rounded-lg border border-border bg-background text-sm"
                placeholder="Search KPIs, worksheets…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <select className="px-3 py-2 rounded-lg border border-border bg-background text-sm" value={filterConfidence} onChange={e => setFilterConfidence(e.target.value)}>
              <option value="all">All Confidence</option>
              <option value="high">High (≥80%)</option>
              <option value="medium">Medium (50-79%)</option>
              <option value="low">Low (&lt;50%)</option>
            </select>
            {dashboardNames.length > 2 && (
              <select className="px-3 py-2 rounded-lg border border-border bg-background text-sm min-w-[160px]" value={filterDashboard} onChange={e => setFilterDashboard(e.target.value)}>
                {dashboardNames.map(d => <option key={d} value={d}>{d === 'all' ? 'All Dashboards' : d}</option>)}
              </select>
            )}
            {workbookNames.length > 2 && (
              <select className="px-3 py-2 rounded-lg border border-border bg-background text-sm min-w-[160px]" value={filterWorkbook} onChange={e => setFilterWorkbook(e.target.value)}>
                {workbookNames.map(w => <option key={w} value={w}>{w === 'all' ? 'All Workbooks' : w}</option>)}
              </select>
            )}
            {(search || filterStatus !== 'all' || filterConfidence !== 'all' || filterDashboard !== 'all' || filterWorkbook !== 'all') && (
              <button
                className="px-3 py-2 text-xs rounded-lg border border-border text-muted-foreground hover:bg-muted transition-colors"
                onClick={() => { setSearch(''); setFilterStatus('all'); setFilterConfidence('all'); setFilterDashboard('all'); setFilterWorkbook('all'); }}
              >
                Clear All
              </button>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-2">
            Showing {filteredMappings.length} of {allMappings.length} mappings
            {changesCount > 0 && <span className="text-amber-400 ml-2">· {changesCount} unsaved change{changesCount !== 1 ? 's' : ''}</span>}
          </p>
        </CardContent>
      </Card>

      {/* ── Enterprise Data Grid ─────────────────────────── */}
      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground gap-2">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading governance data…
        </div>
      ) : filteredMappings.length === 0 ? (
        <Card>
          <CardContent className="py-16 text-center">
            <BookOpen className="w-10 h-10 text-muted-foreground/30 mx-auto mb-3" />
            <p className="text-sm text-muted-foreground">No KPI mappings found. Upload and approve a workbook scope to begin.</p>
          </CardContent>
        </Card>
      ) : (
        <Card className="overflow-hidden">
          {/* Table Header */}
          <div className="grid grid-cols-12 px-4 py-3 bg-muted/30 border-b border-border text-[10px] font-semibold uppercase tracking-wider text-muted-foreground sticky top-0 z-10">
            <span className="col-span-1"></span>
            <span className="col-span-2">Report KPI</span>
            <span className="col-span-2">Suggested Ontology KPI</span>
            <span className="col-span-1">Similarity</span>
            <span className="col-span-1">Confidence</span>
            <span className="col-span-1">Type</span>
            <span className="col-span-1">Status</span>
            <span className="col-span-1">Reviewer</span>
            <span className="col-span-2 text-center">Actions</span>
          </div>

          {/* Table Body */}
          <div className="divide-y divide-border">
            {filteredMappings.map((m) => {
              const isExpanded = expandedRow === m.mapping_id;
              const hasPending = !!pendingChanges[m.mapping_id];
              const isReviewing = activeReview === m.mapping_id;
              const isNewKpiOpen = showNewKpi === m.mapping_id;

              return (
                <div key={m.mapping_id} className={`${hasPending ? 'bg-amber-500/5 border-l-2 border-l-amber-500' : ''}`}>
                  {/* Main Row */}
                  <div
                    className="grid grid-cols-12 px-4 py-3 items-center hover:bg-accent/20 transition-colors text-sm cursor-pointer"
                    onClick={() => {
                      const next = isExpanded ? null : m.mapping_id;
                      setExpandedRow(next);
                      if (next) fetchAudit(m.mapping_id);
                    }}
                  >
                    {/* Expand Arrow */}
                    <div className="col-span-1 flex items-center gap-1">
                      {isExpanded ? <ChevronDown className="w-4 h-4 text-primary" /> : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
                      {m.worksheet_name && (
                        <span title={m.worksheet_name}><BarChart2 className="w-3.5 h-3.5 text-indigo-400" /></span>
                      )}
                    </div>

                    {/* Report KPI */}
                    <div className="col-span-2 min-w-0">
                      <p className="font-semibold text-foreground truncate text-xs">{m.report_kpi_name}</p>
                      <p className="text-[10px] text-muted-foreground truncate">{m.dashboardName}</p>
                    </div>

                    {/* Ontology KPI */}
                    <div className="col-span-2 min-w-0">
                      {m.canonical_kpi ? (
                        <div>
                          <p className="font-medium text-indigo-400 truncate text-xs">{m.canonical_kpi.name}</p>
                          <p className="text-[10px] text-muted-foreground truncate">{m.canonical_kpi.subdomain?.replace(/_/g, ' ')}</p>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground/50 italic">No match</span>
                      )}
                    </div>

                    {/* Similarity */}
                    <div className="col-span-1" onClick={e => e.stopPropagation()}>
                      {similarityBar(m.similarity_score)}
                    </div>

                    {/* Confidence */}
                    <div className="col-span-1" onClick={e => e.stopPropagation()}>
                      {confidenceBadge(m.confidence_score)}
                    </div>

                    {/* Mapping Type */}
                    <div className="col-span-1">
                      {m.mapping_type ? (
                        <span className={`px-1.5 py-0.5 rounded text-[9px] font-medium border ${mappingTypeStyles[m.mapping_type] || 'bg-muted text-muted-foreground'}`}>
                          {m.mapping_type.replace(/_/g, ' ')}
                        </span>
                      ) : <span className="text-muted-foreground/40 text-[10px]">—</span>}
                    </div>

                    {/* Status */}
                    <div className="col-span-1">
                      {hasPending ? (
                        <Badge className="bg-amber-500/15 text-amber-400 border-amber-500/20 text-[10px] gap-1">
                          <Edit3 className="w-3 h-3" />Pending
                        </Badge>
                      ) : statusBadge(m.mapping_status)}
                    </div>

                    {/* Reviewer */}
                    <div className="col-span-1">
                      <span className="text-[10px] text-muted-foreground font-mono truncate block">
                        {m.resolved_by || '—'}
                      </span>
                    </div>

                    {/* Actions */}
                    <div className="col-span-2 flex justify-center gap-1" onClick={e => e.stopPropagation()}>
                      {(m.mapping_status === 'pending_review' || m.mapping_status === 'not_found') && !hasPending && (
                        <>
                          <button
                            className="p-1 rounded hover:bg-emerald-500/10 text-emerald-500 transition-colors"
                            title="Approve"
                            onClick={() => handleInlineAction(m.mapping_id, 'accept')}
                          >
                            <Check className="w-4 h-4" />
                          </button>
                          <button
                            className="p-1 rounded hover:bg-red-500/10 text-red-500 transition-colors"
                            title="Reject"
                            onClick={() => handleInlineAction(m.mapping_id, 'reject')}
                          >
                            <Ban className="w-4 h-4" />
                          </button>
                          <button
                            className="p-1 rounded hover:bg-indigo-500/10 text-indigo-500 transition-colors"
                            title="Override / Reassign"
                            onClick={() => handleInlineAction(m.mapping_id, 'reassign')}
                          >
                            <ArrowRightLeft className="w-4 h-4" />
                          </button>
                          {m.mapping_status === 'not_found' && (
                            <button
                              className="p-1 rounded hover:bg-purple-500/10 text-purple-500 transition-colors"
                              title="Create New KPI"
                              onClick={() => {
                                setShowNewKpi(m.mapping_id);
                                setNewKpiForm({ name: m.report_kpi_name, definition: m.report_kpi_definition || '', lob: '', sector: '', subdomain: '' });
                              }}
                            >
                              <Plus className="w-4 h-4" />
                            </button>
                          )}
                        </>
                      )}
                      {hasPending && (
                        <button
                          className="text-[10px] text-muted-foreground hover:text-foreground transition-colors underline"
                          onClick={() => {
                            const next = { ...pendingChanges };
                            delete next[m.mapping_id];
                            setPendingChanges(next);
                          }}
                        >
                          Undo
                        </button>
                      )}
                    </div>
                  </div>

                  {/* ── Inline Review Justification Panel ───────── */}
                  {isReviewing && (
                    <div className="px-6 py-3 bg-muted/20 border-t border-border/50 animate-in slide-in-from-top-2 duration-200">
                      <div className="flex items-start gap-3">
                        <MessageSquare className="w-4 h-4 text-amber-400 mt-1 shrink-0" />
                        <div className="flex-1 space-y-2">
                          <p className="text-xs font-semibold text-foreground">
                            {pendingChanges[m.mapping_id]?.action === 'accept' ? 'Approve Justification' :
                             pendingChanges[m.mapping_id]?.action === 'reject' ? 'Reject Reason' : 'Override Justification'}
                            <span className="text-red-400 ml-0.5">*</span>
                          </p>

                          {/* Reassign: show top 5 alternatives + dropdown */}
                          {(!pendingChanges[m.mapping_id] || pendingChanges[m.mapping_id]?.action === 'reassign') && (
                            <div className="space-y-2">
                              {m.alternative_candidates && m.alternative_candidates.length > 0 && (
                                <div className="space-y-1">
                                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold">Top 5 Suggestions</p>
                                  <div className="flex flex-wrap gap-1.5">
                                    {m.alternative_candidates.slice(0, 5).map(c => (
                                      <button
                                        key={c.kpi_id}
                                        onClick={() => setReassignKpiId(c.kpi_id)}
                                        className={`px-2 py-1 rounded text-[11px] border transition-all ${
                                          reassignKpiId === c.kpi_id
                                            ? 'border-primary bg-primary/10 text-primary font-medium'
                                            : 'border-border bg-card hover:bg-muted text-foreground'
                                        }`}
                                      >
                                        {c.name} <span className="text-muted-foreground ml-1">{Math.round(c.score * 100)}%</span>
                                      </button>
                                    ))}
                                  </div>
                                </div>
                              )}
                              <select
                                className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                                value={reassignKpiId}
                                onChange={e => setReassignKpiId(e.target.value)}
                              >
                                <option value="">Choose ontology KPI…</option>
                                {canonicalKpis.map(k => <option key={k.kpi_id} value={k.kpi_id}>{k.name}</option>)}
                              </select>
                            </div>
                          )}

                          <textarea
                            className="w-full px-3 py-2 text-sm rounded-lg border border-border bg-background min-h-[60px] resize-none"
                            placeholder="Business reason / justification (mandatory)"
                            value={reviewJustification}
                            onChange={e => setReviewJustification(e.target.value)}
                          />
                          <div className="flex gap-2">
                            <Button
                              size="sm"
                              disabled={!reviewJustification.trim() || (pendingChanges[m.mapping_id]?.action === 'reassign' && !reassignKpiId)}
                              onClick={() => confirmAction(m.mapping_id, pendingChanges[m.mapping_id]?.action || 'accept')}
                            >
                              Confirm
                            </Button>
                            <Button variant="outline" size="sm" onClick={() => {
                              setActiveReview(null);
                              const next = { ...pendingChanges };
                              delete next[m.mapping_id];
                              setPendingChanges(next);
                            }}>
                              Cancel
                            </Button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* ── Inline New KPI Creation ──────────────────── */}
                  {isNewKpiOpen && (
                    <div className="px-6 py-4 bg-purple-500/5 border-t border-purple-500/20 animate-in slide-in-from-top-2 duration-200">
                      <p className="text-sm font-semibold flex items-center gap-2 mb-3">
                        <Sparkles className="w-4 h-4 text-purple-400" /> Create New KPI
                      </p>
                      <div className="grid grid-cols-2 gap-3">
                        <input className="px-3 py-2 text-sm rounded-lg border border-border bg-background" value={newKpiForm.name} onChange={e => setNewKpiForm(p => ({ ...p, name: e.target.value }))} placeholder="KPI Name *" />
                        <input className="px-3 py-2 text-sm rounded-lg border border-border bg-background" value={newKpiForm.lob} onChange={e => setNewKpiForm(p => ({ ...p, lob: e.target.value }))} placeholder="Line of Business" />
                        <input className="px-3 py-2 text-sm rounded-lg border border-border bg-background" value={newKpiForm.sector} onChange={e => setNewKpiForm(p => ({ ...p, sector: e.target.value }))} placeholder="Sector" />
                        <input className="px-3 py-2 text-sm rounded-lg border border-border bg-background" value={newKpiForm.subdomain} onChange={e => setNewKpiForm(p => ({ ...p, subdomain: e.target.value }))} placeholder="Business Function" />
                        <textarea className="col-span-2 px-3 py-2 text-sm rounded-lg border border-border bg-background min-h-[60px]" value={newKpiForm.definition} onChange={e => setNewKpiForm(p => ({ ...p, definition: e.target.value }))} placeholder="Definition *" />
                      </div>
                      <div className="flex gap-2 mt-3">
                        <Button size="sm" disabled={saving || !newKpiForm.name.trim() || !newKpiForm.definition.trim()} onClick={() => promoteNewKpi(m.mapping_id)}>
                          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin mr-1" /> : <Plus className="w-3.5 h-3.5 mr-1" />}
                          Create & Map
                        </Button>
                        <Button variant="outline" size="sm" onClick={() => setShowNewKpi(null)}>Cancel</Button>
                      </div>
                    </div>
                  )}

                  {/* ── Expandable Row Details ───────────────────── */}
                  {isExpanded && (
                    <div className="px-6 py-4 bg-card/50 border-t border-border/50 animate-in slide-in-from-top-2 duration-200 space-y-4">
                      {/* Visual Info */}
                      {m.worksheet_name && (
                        <div className="flex items-start gap-3 p-3 rounded-lg bg-muted/30 border border-border/50">
                          <BarChart2 className="w-5 h-5 text-indigo-400 shrink-0 mt-0.5" />
                          <div>
                            <p className="text-xs font-semibold">Visual: {m.worksheet_name}</p>
                            <p className="text-[10px] text-muted-foreground">Dashboard: {m.dashboardName} · Workbook: {m.workbookName}</p>
                          </div>
                        </div>
                      )}

                      {/* Detail Grid */}
                      <div className="grid grid-cols-2 gap-4 text-xs">
                        <div className="space-y-3">
                          <div>
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Current Report KPI</p>
                            <p className="font-semibold">{m.report_kpi_name}</p>
                          </div>
                          {m.report_kpi_definition && (
                            <div>
                              <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Formula / Definition</p>
                              <code className="text-[11px] bg-muted/50 px-2 py-1 rounded border border-border/50 block break-all">{m.report_kpi_definition}</code>
                            </div>
                          )}
                          {m.report_kpi_lineage && m.report_kpi_lineage.length > 0 && (
                            <div>
                              <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Lineage</p>
                              <p className="font-mono text-muted-foreground text-[11px]">{m.report_kpi_lineage.join(' → ')}</p>
                            </div>
                          )}
                        </div>
                        <div className="space-y-3">
                          {m.canonical_kpi && (
                            <>
                              <div>
                                <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Suggested Ontology KPI</p>
                                <p className="font-semibold text-indigo-400">{m.canonical_kpi.name}</p>
                              </div>
                              {m.canonical_kpi.definition && (
                                <div>
                                  <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Business Definition</p>
                                  <p className="text-muted-foreground">{m.canonical_kpi.definition}</p>
                                </div>
                              )}
                              <div className="flex gap-4">
                                {m.canonical_kpi.sector && (
                                  <div><p className="text-[10px] text-muted-foreground">Sector</p><p className="font-medium">{m.canonical_kpi.sector}</p></div>
                                )}
                                {m.canonical_kpi.subdomain && (
                                  <div><p className="text-[10px] text-muted-foreground">Function</p><p className="font-medium">{m.canonical_kpi.subdomain.replace(/_/g, ' ')}</p></div>
                                )}
                              </div>
                            </>
                          )}
                        </div>
                      </div>

                      {/* Similarity / Confidence Explanation */}
                      {(m.similarity_rationale || m.confidence_rationale) && (
                        <div className="p-3 rounded-lg bg-muted/30 text-xs space-y-2 border border-border/50">
                          {m.similarity_rationale && (
                            <div>
                              <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-0.5">LLM Rationale / Similarity Explanation</p>
                              <p className="text-muted-foreground">{m.similarity_rationale}</p>
                            </div>
                          )}
                          {m.confidence_rationale && (
                            <div>
                              <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-0.5">Confidence Rationale</p>
                              <p className="text-muted-foreground font-mono text-[11px]">{m.confidence_rationale}</p>
                            </div>
                          )}
                          {m.model_used && (
                            <p className="text-[10px] text-muted-foreground/60">Model: <span className="font-mono bg-muted px-1 rounded">{m.model_used}</span></p>
                          )}
                        </div>
                      )}

                      {/* Alternative Candidates */}
                      {m.alternative_candidates && m.alternative_candidates.length > 0 && (
                        <div>
                          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-2">Alternative Ontology Candidates (Top 5)</p>
                          <div className="flex flex-wrap gap-2">
                            {m.alternative_candidates.slice(0, 5).map(c => (
                              <div key={c.kpi_id} className="px-3 py-1.5 rounded-lg border border-border bg-card text-xs flex items-center gap-2">
                                <span className="font-medium">{c.name}</span>
                                <span className={`font-mono text-[10px] font-bold ${c.score >= 0.8 ? 'text-emerald-400' : c.score >= 0.5 ? 'text-amber-400' : 'text-red-400'}`}>
                                  {Math.round(c.score * 100)}%
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}

                      {/* Audit History */}
                      <div className="border border-border/60 rounded-lg overflow-hidden">
                        <button
                          type="button"
                          onClick={() => setShowAuditFor(showAuditFor === m.mapping_id ? null : m.mapping_id)}
                          className="w-full px-3 py-2 bg-muted/40 hover:bg-muted/60 flex items-center justify-between text-xs font-semibold text-muted-foreground transition-colors"
                        >
                          <span className="flex items-center gap-1.5">
                            <History className="w-3.5 h-3.5 text-sky-400" />
                            Audit History ({auditLogs[m.mapping_id]?.length || 0})
                          </span>
                          <span className="text-[10px]">{showAuditFor === m.mapping_id ? 'Hide' : 'Show'}</span>
                        </button>
                        {showAuditFor === m.mapping_id && (
                          <div className="p-2 space-y-1.5 max-h-40 overflow-y-auto divide-y divide-border/40 bg-background">
                            {(auditLogs[m.mapping_id] || []).length === 0 ? (
                              <p className="text-[10px] text-muted-foreground italic p-2">No audit entries yet</p>
                            ) : (
                              (auditLogs[m.mapping_id] || []).map(log => (
                                <div key={log.id} className="pt-1.5 first:pt-0 space-y-0.5 text-xs">
                                  <div className="flex items-center justify-between text-[10px]">
                                    <span className="font-mono text-primary">{log.field_changed}</span>
                                    <span className="text-muted-foreground">{log.timestamp?.slice(0, 16).replace('T', ' ')}</span>
                                  </div>
                                  <p className="text-muted-foreground">
                                    <span className="line-through opacity-70">{log.original_value || 'None'}</span> → <span className="font-medium text-foreground">{log.new_value}</span>
                                  </p>
                                  <p className="text-[10px] italic text-muted-foreground">
                                    Reason: {log.reason} ({log.approval_user})
                                  </p>
                                </div>
                              ))
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}
