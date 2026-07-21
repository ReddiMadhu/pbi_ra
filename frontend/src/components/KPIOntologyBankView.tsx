import { useEffect, useState, useMemo, useCallback } from 'react';
import { BookOpen, Search, Loader2, AlertCircle, Filter, Plus, Save, Sparkles, Check } from 'lucide-react';
import { API_BASE_URL } from '@/config';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface CanonicalKPI {
  kpi_id: string;
  name: string;
  definition: string;
  domain: string;
  sector: string;
  subdomain: string;
  line_of_business?: string;
  aliases: string[];
  aggregation_type: string;
  status: 'active' | 'stale';
  is_active_sector?: boolean;
  created_by: string;
  created_at: string;
  embedding_model?: string;
}

interface Taxonomy {
  sectors: string[];
  active_sectors: string[];
  subdomains_by_sector: Record<string, string[]>;
  subdomain_display_labels?: Record<string, string>;
}

function norm(s: string | null | undefined): string {
  return (s || '').trim().toLowerCase();
}

export function KPIOntologyBankView({ onNavigate }: { onNavigate?: (view: any) => void }) {
  const [kpis, setKpis] = useState<CanonicalKPI[]>([]);
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sectorFilter, setSectorFilter] = useState('all');
  const [subdomainFilter, setSubdomainFilter] = useState('all');
  const [selectedKpi, setSelectedKpi] = useState<CanonicalKPI | null>(null);

  // New KPI Form State
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [createForm, setCreateForm] = useState({
    name: '',
    definition: '',
    description: '',
    formula: '',
    sector: 'insurance',
    subdomain: 'service_and_operations',
    lob: '',
    aliases: '',
  });
  const [submitting, setSubmitting] = useState(false);

  const labelSubdomain = useCallback(
    (key: string | null | undefined) => {
      if (!key) return '—';
      return taxonomy?.subdomain_display_labels?.[key] ?? key;
    },
    [taxonomy],
  );

  const matchesSubdomain = useCallback(
    (kpiSub: string | null | undefined, filter: string) => {
      if (filter === 'all') return true;
      const raw = norm(kpiSub);
      if (!raw) return false;
      const f = norm(filter);
      if (raw === f) return true;
      const filterLabel = norm(labelSubdomain(filter));
      const kpiLabel = norm(labelSubdomain(kpiSub));
      if (raw === filterLabel || kpiLabel === f || kpiLabel === filterLabel) return true;
      const compact = (s: string) => s.replace(/[&_\s-]+/g, '');
      return compact(raw) === compact(f) || compact(raw) === compact(filterLabel);
    },
    [labelSubdomain],
  );

  const matchesSector = useCallback((kpiSector: string | null | undefined, filter: string) => {
    if (filter === 'all') return true;
    return norm(kpiSector) === norm(filter);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [kpiRes, taxRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/ontology/kpis?limit=5000&status=active`),
        fetch(`${API_BASE_URL}/api/v1/ontology/taxonomy`),
      ]);
      const kpiData = await kpiRes.json();
      const taxData = await taxRes.json();
      setKpis(Array.isArray(kpiData) ? kpiData : []);
      setTaxonomy(taxData);
    } catch {
      setKpis([]);
      setTaxonomy(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const sectors = useMemo(() => {
    const fromTax = taxonomy?.sectors ?? [];
    const fromKpis = kpis.map((k) => k.sector).filter(Boolean);
    return ['all', ...Array.from(new Set([...fromTax, ...fromKpis]))];
  }, [kpis, taxonomy]);

  const subdomains = useMemo(() => {
    if (sectorFilter === 'all') {
      const active = taxonomy?.active_sectors ?? ['insurance'];
      const fromActive = active.flatMap((s) => taxonomy?.subdomains_by_sector?.[s] ?? []);
      const fromTax = Object.values(taxonomy?.subdomains_by_sector ?? {}).flat();
      const fromKpis = kpis.map((k) => k.subdomain).filter(Boolean);
      return ['all', ...Array.from(new Set([...fromActive, ...fromTax, ...fromKpis]))];
    }
    const fromTax = taxonomy?.subdomains_by_sector?.[sectorFilter] ?? [];
    const fromKpis = kpis
      .filter((k) => matchesSector(k.sector, sectorFilter))
      .map((k) => k.subdomain)
      .filter(Boolean);
    return ['all', ...Array.from(new Set([...fromTax, ...fromKpis]))];
  }, [kpis, taxonomy, sectorFilter, matchesSector]);

  const sectorCounts = useMemo(() => {
    const counts: Record<string, number> = { all: kpis.length };
    for (const s of sectors) {
      if (s === 'all') continue;
      counts[s] = kpis.filter((k) => matchesSector(k.sector, s)).length;
    }
    return counts;
  }, [kpis, sectors, matchesSector]);

  const subdomainCounts = useMemo(() => {
    const pool = sectorFilter === 'all'
      ? kpis
      : kpis.filter((k) => matchesSector(k.sector, sectorFilter));
    const counts: Record<string, number> = { all: pool.length };
    for (const d of subdomains) {
      if (d === 'all') continue;
      counts[d] = pool.filter((k) => matchesSubdomain(k.subdomain, d)).length;
    }
    return counts;
  }, [kpis, subdomains, sectorFilter, matchesSector, matchesSubdomain]);

  const filteredKpis = useMemo(() => {
    return kpis.filter((k) => {
      const q = search.toLowerCase();
      const matchSearch =
        !q ||
        k.name.toLowerCase().includes(q) ||
        (k.definition || '').toLowerCase().includes(q) ||
        k.aliases?.some((a) => a.toLowerCase().includes(q)) ||
        labelSubdomain(k.subdomain).toLowerCase().includes(q) ||
        (k.domain || '').toLowerCase().includes(q);
      const matchSector = matchesSector(k.sector, sectorFilter);
      const matchSubdomain = matchesSubdomain(k.subdomain, subdomainFilter);
      return matchSearch && matchSector && matchSubdomain;
    });
  }, [kpis, search, sectorFilter, subdomainFilter, labelSubdomain, matchesSector, matchesSubdomain]);

  const isSectorInactive = (sector: string) =>
    taxonomy?.active_sectors ? !taxonomy.active_sectors.includes(sector) : false;

  const filtersActive = sectorFilter !== 'all' || subdomainFilter !== 'all' || Boolean(search.trim());

  const handleCreateKpi = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!createForm.name.trim() || !createForm.definition.trim()) {
      alert('Please fill out Name and Definition.');
      return;
    }
    setSubmitting(true);
    try {
      const aliasesList = createForm.aliases
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);

      const res = await fetch(`${API_BASE_URL}/api/v1/ontology/kpis`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: createForm.name.trim(),
          definition: `${createForm.definition.trim()} ${createForm.description ? `(Description: ${createForm.description.trim()})` : ''} ${createForm.formula ? `(Formula: ${createForm.formula.trim()})` : ''}`,
          sector: createForm.sector,
          subdomain: createForm.subdomain,
          line_of_business: createForm.lob.trim() || undefined,
          aliases: aliasesList,
          created_by: localStorage.getItem('governance_analyst_id') || 'analyst_lead',
        }),
      });

      if (!res.ok) {
        const errorData = await res.json();
        throw new Error(errorData.detail || 'Failed to create KPI');
      }

      setCreateForm({
        name: '',
        definition: '',
        description: '',
        formula: '',
        sector: 'insurance',
        subdomain: 'service_and_operations',
        lob: '',
        aliases: '',
      });
      setShowCreateForm(false);
      await load();
    } catch (err: any) {
      alert(err.message || 'An error occurred while creating the KPI.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-primary" />
            KPI Ontology
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Browse corporate canonical KPIs, taxonomy classifications, and add new canonical definitions
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <Button
            onClick={() => setShowCreateForm(!showCreateForm)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" />
            Create New KPI
          </Button>
        </div>
      </div>

      {/* Inline Create Form (Collapsible, No popup, No navigation) */}
      {showCreateForm && (
        <Card className="border-indigo-500/20 bg-indigo-500/5 animate-in slide-in-from-top-4 duration-300">
          <CardHeader className="pb-3">
            <CardTitle className="text-sm font-bold flex items-center gap-2 text-indigo-400">
              <Sparkles className="w-4 h-4 text-indigo-400" />
              Define New Canonical KPI
            </CardTitle>
          </CardHeader>
          <CardContent>
            <form onSubmit={handleCreateKpi} className="space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">KPI Name *</label>
                  <input
                    required
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.name}
                    onChange={(e) => setCreateForm({ ...createForm, name: e.target.value })}
                    placeholder="e.g. Underwriting Loss Ratio"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Line of Business</label>
                  <input
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.lob}
                    onChange={(e) => setCreateForm({ ...createForm, lob: e.target.value })}
                    placeholder="e.g. Commercial Property, Auto"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Sector</label>
                  <select
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.sector}
                    onChange={(e) => setCreateForm({ ...createForm, sector: e.target.value })}
                  >
                    <option value="insurance">Insurance</option>
                    <option value="banking">Banking</option>
                    <option value="finance">Finance & Accounting</option>
                    <option value="operational">Operations / HR / IT</option>
                  </select>
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Business Function / Subdomain</label>
                  <select
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.subdomain}
                    onChange={(e) => setCreateForm({ ...createForm, subdomain: e.target.value })}
                  >
                    <option value="marketing">Marketing</option>
                    <option value="distribution">Distribution</option>
                    <option value="actuarial_and_risk">Actuarial & Risk</option>
                    <option value="underwriting">Underwriting</option>
                    <option value="claims_litigation">Claims & Litigation</option>
                    <option value="service_and_operations">Service & Operations</option>
                    <option value="cx_and_digital">CX & Digital</option>
                    <option value="retail">Retail</option>
                    <option value="corporate">Corporate</option>
                    <option value="risk">Risk</option>
                    <option value="shared">Shared</option>
                    <option value="accounting">Accounting</option>
                    <option value="treasury">Treasury</option>
                    <option value="fp_and_a">FP&A</option>
                    <option value="supply_chain">Supply Chain</option>
                    <option value="hr">HR</option>
                    <option value="it_ops">IT Ops</option>
                  </select>
                </div>
                <div className="col-span-1 md:col-span-2 space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Definition *</label>
                  <textarea
                    required
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm min-h-[60px]"
                    value={createForm.definition}
                    onChange={(e) => setCreateForm({ ...createForm, definition: e.target.value })}
                    placeholder="Provide the formal regulatory or business definition..."
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Description</label>
                  <input
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.description}
                    onChange={(e) => setCreateForm({ ...createForm, description: e.target.value })}
                    placeholder="Short description of purpose or goals"
                  />
                </div>
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Formula</label>
                  <input
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.formula}
                    onChange={(e) => setCreateForm({ ...createForm, formula: e.target.value })}
                    placeholder="e.g. Net Incurred Claims / Net Earned Premium"
                  />
                </div>
                <div className="col-span-1 md:col-span-2 space-y-1.5">
                  <label className="text-xs font-semibold text-muted-foreground">Aliases (Comma-separated)</label>
                  <input
                    className="w-full px-3 py-2 rounded-lg border border-border bg-background text-sm"
                    value={createForm.aliases}
                    onChange={(e) => setCreateForm({ ...createForm, aliases: e.target.value })}
                    placeholder="e.g. Loss Ratio, Loss Pct, Claim Ratio"
                  />
                </div>
              </div>
              <div className="flex gap-2 justify-end pt-2">
                <Button variant="outline" size="sm" type="button" onClick={() => setShowCreateForm(false)}>
                  Cancel
                </Button>
                <Button size="sm" type="submit" disabled={submitting} className="bg-indigo-600 hover:bg-indigo-700">
                  {submitting ? <Loader2 className="w-4 h-4 animate-spin mr-1.5" /> : <Save className="w-4 h-4 mr-1.5" />}
                  Save to Ontology
                </Button>
              </div>
            </form>
          </CardContent>
        </Card>
      )}

      {/* Filters */}
      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            className="w-full pl-10 pr-4 py-2 rounded-lg border border-border bg-background text-sm"
            placeholder="Search corporate KPIs…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Filter className="w-4 h-4 text-muted-foreground" />
          <select
            className="px-3 py-2 rounded-lg border border-border bg-background text-sm animate-in fade-in"
            value={sectorFilter}
            onChange={(e) => {
              setSectorFilter(e.target.value);
              setSubdomainFilter('all');
            }}
          >
            {sectors.map((s) => (
              <option key={s} value={s}>
                {s === 'all'
                  ? `All sectors (${sectorCounts.all ?? 0})`
                  : `${s}${isSectorInactive(s) ? ' (inactive)' : ''} (${sectorCounts[s] ?? 0})`}
              </option>
            ))}
          </select>
          <select
            className="px-3 py-2 rounded-lg border border-border bg-background text-sm min-w-[200px]"
            value={subdomainFilter}
            onChange={(e) => setSubdomainFilter(e.target.value)}
          >
            {subdomains.map((d) => (
              <option key={d} value={d}>
                {d === 'all'
                  ? `All subdomains (${subdomainCounts.all ?? 0})`
                  : `${labelSubdomain(d)} (${subdomainCounts[d] ?? 0})`}
              </option>
            ))}
          </select>
          {filtersActive && (
            <button
              type="button"
              className="px-3 py-2 text-xs rounded-lg border border-border text-muted-foreground hover:bg-muted"
              onClick={() => {
                setSectorFilter('all');
                setSubdomainFilter('all');
                setSearch('');
              }}
            >
              Clear filters
            </button>
          )}
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground gap-2">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading KPI ontology bank…
        </div>
      ) : (
        <div className="grid gap-3">
          {filteredKpis.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
              {filtersActive
                ? 'No KPIs match the selected sector / subdomain filters.'
                : 'No canonical KPIs yet. Create a new KPI using the form above.'}
            </div>
          ) : (
            filteredKpis.map((kpi) => (
              <div
                key={kpi.kpi_id}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedKpi(kpi)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') setSelectedKpi(kpi);
                }}
                className="p-4 rounded-xl border border-border bg-card hover:border-primary/30 cursor-pointer transition-all text-left"
              >
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="font-semibold">{kpi.name}</span>
                  <Badge
                    variant="outline"
                    className="text-[10px] cursor-pointer"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (kpi.sector) setSectorFilter(kpi.sector);
                      if (kpi.subdomain) {
                        const taxKeys = taxonomy?.subdomains_by_sector?.[kpi.sector || ''] ?? [];
                        const hit =
                          taxKeys.find((k) => matchesSubdomain(kpi.subdomain, k)) || kpi.subdomain;
                        setSubdomainFilter(hit);
                      }
                    }}
                  >
                    {kpi.sector}/{labelSubdomain(kpi.subdomain)}
                  </Badge>
                  {kpi.is_active_sector === false && (
                    <Badge variant="outline" className="text-[10px] text-muted-foreground">inactive sector</Badge>
                  )}
                  {kpi.created_by !== 'system' && kpi.created_by !== 'seed' && (
                    <Badge className="bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 text-[10px] gap-1">
                      User Added
                    </Badge>
                  )}
                  <Badge variant={kpi.status === 'active' ? 'default' : 'outline'} className="text-[10px] ml-auto">
                    {kpi.status}
                  </Badge>
                </div>
                <p className="text-sm text-muted-foreground line-clamp-2">{kpi.definition}</p>
                {kpi.aliases?.length > 0 && (
                  <p className="text-xs text-muted-foreground mt-2">Aliases: {kpi.aliases.join(', ')}</p>
                )}
              </div>
            ))
          )}
        </div>
      )}

      {selectedKpi && (
        <div className="fixed inset-0 z-40 flex justify-end">
          <div className="absolute inset-0 bg-black/40" onClick={() => setSelectedKpi(null)} />
          <div className="relative w-full max-w-md bg-background border-l border-border shadow-xl p-6 overflow-y-auto">
            <h3 className="text-lg font-bold mb-4">{selectedKpi.name}</h3>
            <div className="space-y-3 text-sm">
              <div><span className="text-muted-foreground">Sector:</span> {selectedKpi.sector}</div>
              <div>
                <span className="text-muted-foreground">Subdomain:</span>{' '}
                {labelSubdomain(selectedKpi.subdomain)}
                {selectedKpi.subdomain && selectedKpi.subdomain !== labelSubdomain(selectedKpi.subdomain) && (
                  <span className="text-xs text-muted-foreground ml-1">(keys: {selectedKpi.subdomain})</span>
                )}
              </div>
              {selectedKpi.line_of_business && (
                <div><span className="text-muted-foreground">Line of Business:</span> {selectedKpi.line_of_business}</div>
              )}
              <div><span className="text-muted-foreground">Domain:</span> {selectedKpi.domain}</div>
              <div><span className="text-muted-foreground">Aggregation:</span> {selectedKpi.aggregation_type}</div>
              <div><span className="text-muted-foreground">Definition:</span> {selectedKpi.definition}</div>
              {selectedKpi.aliases?.length > 0 && (
                <div><span className="text-muted-foreground">Aliases:</span> {selectedKpi.aliases.join(', ')}</div>
              )}
              {selectedKpi.embedding_model && (
                <div>
                  <span className="text-muted-foreground">Embedding Model:</span>{' '}
                  <span className="font-mono bg-muted px-1.5 py-0.5 rounded text-xs">{selectedKpi.embedding_model}</span>
                </div>
              )}
              <div className="text-xs text-muted-foreground pt-2 border-t border-border">
                Created by {selectedKpi.created_by} · {selectedKpi.created_at?.slice(0, 10)}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
