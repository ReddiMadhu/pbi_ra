import { useEffect, useState, useMemo } from 'react';
import { BookOpen, Search, Loader2, AlertCircle, Filter } from 'lucide-react';
import { API_BASE_URL } from '@/config';
import { HITLResolutionPanel, MappingRow } from './HITLResolutionPanel';
import { Badge } from './ui/badge';

interface CanonicalKPI {
  kpi_id: string;
  name: string;
  definition: string;
  domain: string;
  sector: string;
  subdomain: string;
  aliases: string[];
  aggregation_type: string;
  status: 'active' | 'stale';
  is_active_sector?: boolean;
  created_by: string;
  created_at: string;
}

interface Taxonomy {
  sectors: string[];
  active_sectors: string[];
  subdomains_by_sector: Record<string, string[]>;
  subdomain_display_labels?: Record<string, string>;
}

type Tab = 'bank' | 'pending_review' | 'not_found';

export function OntologyBankView({ filterReportId }: { filterReportId?: string }) {
  const [tab, setTab] = useState<Tab>(filterReportId ? 'pending_review' : 'bank');
  const [kpis, setKpis] = useState<CanonicalKPI[]>([]);
  const [mappings, setMappings] = useState<MappingRow[]>([]);
  const [taxonomy, setTaxonomy] = useState<Taxonomy | null>(null);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [sectorFilter, setSectorFilter] = useState('all');
  const [subdomainFilter, setSubdomainFilter] = useState('all');
  const [selectedKpi, setSelectedKpi] = useState<CanonicalKPI | null>(null);
  const [resolveMapping, setResolveMapping] = useState<MappingRow | null>(null);

  const load = async () => {
    setLoading(true);
    try {
      const [kpiRes, pendingRes, taxRes] = await Promise.all([
        fetch(`${API_BASE_URL}/api/v1/ontology/kpis?limit=500`),
        fetch(`${API_BASE_URL}/api/v1/ontology/mappings/pending?limit=500`),
        fetch(`${API_BASE_URL}/api/v1/ontology/taxonomy`),
      ]);
      const kpiData = await kpiRes.json();
      const pendingData = await pendingRes.json();
      const taxData = await taxRes.json();
      setKpis(Array.isArray(kpiData) ? kpiData : []);
      setMappings(Array.isArray(pendingData) ? pendingData : []);
      setTaxonomy(taxData);
    } catch {
      setKpis([]);
      setMappings([]);
      setTaxonomy(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const sectors = useMemo(() => {
    const fromTax = taxonomy?.sectors ?? [];
    const fromKpis = kpis.map((k) => k.sector).filter(Boolean);
    return ['all', ...Array.from(new Set([...fromTax, ...fromKpis]))];
  }, [kpis, taxonomy]);

  const subdomains = useMemo(() => {
    if (sectorFilter === 'all') {
      const all = kpis.map((k) => k.subdomain).filter(Boolean);
      return ['all', ...Array.from(new Set(all))];
    }
    const fromTax = taxonomy?.subdomains_by_sector?.[sectorFilter] ?? [];
    const fromKpis = kpis.filter((k) => k.sector === sectorFilter).map((k) => k.subdomain).filter(Boolean);
    return ['all', ...Array.from(new Set([...fromTax, ...fromKpis]))];
  }, [kpis, taxonomy, sectorFilter]);

  const filteredKpis = useMemo(() => {
    return kpis.filter((k) => {
      const q = search.toLowerCase();
      const matchSearch =
        !q ||
        k.name.toLowerCase().includes(q) ||
        k.definition.toLowerCase().includes(q) ||
        k.aliases?.some((a) => a.toLowerCase().includes(q));
      const matchSector = sectorFilter === 'all' || k.sector === sectorFilter;
      const matchSubdomain = subdomainFilter === 'all' || k.subdomain === subdomainFilter;
      return matchSearch && matchSector && matchSubdomain;
    });
  }, [kpis, search, sectorFilter, subdomainFilter]);

  const filteredMappings = useMemo(() => {
    let list = mappings;
    if (filterReportId) list = list.filter((m) => m.report_id === filterReportId);
    if (tab === 'pending_review') list = list.filter((m) => m.mapping_status === 'pending_review');
    if (tab === 'not_found') list = list.filter((m) => m.mapping_status === 'not_found');
    const q = search.toLowerCase();
    if (q) list = list.filter((m) => m.report_kpi_name.toLowerCase().includes(q));
    return list.sort((a, b) => (a.confidence_score || 0) - (b.confidence_score || 0));
  }, [mappings, tab, search, filterReportId]);

  const pendingCount = mappings.filter((m) => m.mapping_status === 'pending_review').length;
  const isSectorInactive = (sector: string) =>
    taxonomy?.active_sectors ? !taxonomy.active_sectors.includes(sector) : false;

  return (
    <div className="space-y-6 animate-in fade-in duration-300">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <BookOpen className="w-6 h-6 text-primary" />
            Ontology Bank
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Browse canonical KPIs by sector and subdomain; resolve HITL mappings
          </p>
        </div>
        {pendingCount > 0 && (
          <Badge variant="outline" className="text-amber-500 border-amber-500/30">
            {pendingCount} pending review
          </Badge>
        )}
      </div>

      <div className="flex flex-wrap gap-2">
        {(['bank', 'pending_review', 'not_found'] as Tab[]).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 rounded-lg text-sm font-medium transition-all ${
              tab === t ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground hover:bg-muted/80'
            }`}
          >
            {t === 'bank' ? 'KPI Bank' : t === 'pending_review' ? 'Pending Review' : 'Not Found'}
          </button>
        ))}
      </div>

      <div className="flex gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[200px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-muted-foreground" />
          <input
            className="w-full pl-10 pr-4 py-2 rounded-lg border border-border bg-background text-sm"
            placeholder="Search KPIs or mappings…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        {tab === 'bank' && (
          <div className="flex items-center gap-2 flex-wrap">
            <Filter className="w-4 h-4 text-muted-foreground" />
            <select
              className="px-3 py-2 rounded-lg border border-border bg-background text-sm"
              value={sectorFilter}
              onChange={(e) => {
                setSectorFilter(e.target.value);
                setSubdomainFilter('all');
              }}
            >
              {sectors.map((s) => (
                <option key={s} value={s}>
                  {s === 'all' ? 'All sectors' : `${s}${isSectorInactive(s) ? ' (inactive)' : ''}`}
                </option>
              ))}
            </select>
            <select
              className="px-3 py-2 rounded-lg border border-border bg-background text-sm"
              value={subdomainFilter}
              onChange={(e) => setSubdomainFilter(e.target.value)}
            >
              {subdomains.map((d) => (
                <option key={d} value={d}>
                  {d === 'all'
                    ? 'All subdomains'
                    : (taxonomy?.subdomain_display_labels?.[d] ?? d)}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20 text-muted-foreground gap-2">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading ontology data…
        </div>
      ) : tab === 'bank' ? (
        <div className="grid gap-3">
          {filteredKpis.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">
              <AlertCircle className="w-8 h-8 mx-auto mb-2 opacity-50" />
              No canonical KPIs yet. Run bootstrap or promote mappings.
            </div>
          ) : (
            filteredKpis.map((kpi) => (
              <div
                key={kpi.kpi_id}
                onClick={() => setSelectedKpi(kpi)}
                className="p-4 rounded-xl border border-border bg-card hover:border-primary/30 cursor-pointer transition-all"
              >
                <div className="flex items-center gap-2 mb-1 flex-wrap">
                  <span className="font-semibold">{kpi.name}</span>
                  <Badge variant="outline" className="text-[10px]">
                    {kpi.sector}/{taxonomy?.subdomain_display_labels?.[kpi.subdomain] ?? kpi.subdomain}
                  </Badge>
                  {kpi.is_active_sector === false && (
                    <Badge variant="outline" className="text-[10px] text-muted-foreground">inactive sector</Badge>
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
      ) : (
        <div className="grid gap-3">
          {filteredMappings.length === 0 ? (
            <div className="text-center py-12 text-muted-foreground">No mappings in this queue.</div>
          ) : (
            filteredMappings.map((m) => (
              <div
                key={m.mapping_id}
                onClick={() => setResolveMapping(m)}
                className="p-4 rounded-xl border border-border bg-card hover:border-amber-500/30 cursor-pointer transition-all"
              >
                <div className="flex items-center gap-2">
                  <span className="font-semibold">{m.report_kpi_name}</span>
                  <Badge variant="outline" className="text-[10px] ml-auto">{m.mapping_status}</Badge>
                </div>
                <p className="text-xs text-muted-foreground mt-1">Report {m.report_id} · {Math.round((m.confidence_score || 0) * 100)}% confidence</p>
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
              <div><span className="text-muted-foreground">Subdomain:</span> {selectedKpi.subdomain}</div>
              <div><span className="text-muted-foreground">Domain:</span> {selectedKpi.domain}</div>
              <div><span className="text-muted-foreground">Aggregation:</span> {selectedKpi.aggregation_type}</div>
              <div><span className="text-muted-foreground">Definition:</span> {selectedKpi.definition}</div>
              {selectedKpi.aliases?.length > 0 && (
                <div><span className="text-muted-foreground">Aliases:</span> {selectedKpi.aliases.join(', ')}</div>
              )}
              <div className="text-xs text-muted-foreground pt-2 border-t border-border">
                Created by {selectedKpi.created_by} · {selectedKpi.created_at?.slice(0, 10)}
              </div>
            </div>
          </div>
        </div>
      )}

      <HITLResolutionPanel
        mapping={resolveMapping}
        canonicalKpis={kpis.map((k) => ({ kpi_id: k.kpi_id, name: k.name }))}
        onClose={() => setResolveMapping(null)}
        onResolved={load}
      />
    </div>
  );
}
