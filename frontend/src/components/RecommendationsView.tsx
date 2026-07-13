import { API_BASE_URL } from '@/config';
import { useState, useEffect } from 'react';
import { 
  ShieldCheck, 
  GitMerge, 
  Trash2, 
  Search, 
  Calendar, 
  Users, 
  Database, 
  Loader2, 
  AlertCircle, 
  ArrowRight,
  TrendingUp,
  X,
  Sparkles,
  Maximize2,
  FileDown
} from 'lucide-react';
import { jsPDF } from 'jspdf';
import { KPIDashboardGraph } from './KPIDashboardGraph';
import { OntologyScoreBadge, OntologyKPIInventory } from './OntologyScoreBadge';

interface DashboardItem {
  id: number;
  name: string;
  workbook_name: string;
  days_ago: number;
  user_groups: string[];
  kpis: string[];
  tables: string[];
  uniqueness: number;
  merge_with?: string;
  reasons: string[];
  common_kpis?: string[];
  common_tables?: string[];
  ontology_overlap_kpis?: string[];
  ontology_inventory?: OntologyKPIInventory;
  summary?: string;
}

interface RecommendationsData {
  keep: DashboardItem[];
  merge: DashboardItem[];
  discard: DashboardItem[];
}

export function RecommendationsView({ cachedData, onCacheData }: { cachedData: RecommendationsData | null; onCacheData: (data: RecommendationsData) => void }) {
  const [data, setData] = useState<RecommendationsData | null>(cachedData);
  const [loading, setLoading] = useState(!cachedData);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [selectedWorkbook, setSelectedWorkbook] = useState<string>('all');
  const [activeTab, setActiveTab] = useState<'all' | 'keep' | 'merge' | 'discard'>('all');
  
  // Modal states for merge review
  const [mergeModalItem, setMergeModalItem] = useState<DashboardItem | null>(null);
  const [matchingItem, setMatchingItem] = useState<DashboardItem | null>(null);
  const [isFullGraphOpen, setIsFullGraphOpen] = useState(false);
  const [decommissionModalItem, setDecommissionModalItem] = useState<DashboardItem | null>(null);
  const [emailDraft, setEmailDraft] = useState<{ to: string; subject: string; body: string; type: 'merge' | 'decommission' } | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  useEffect(() => {
    if (toastMessage) {
      const timer = setTimeout(() => setToastMessage(null), 3000);
      return () => clearTimeout(timer);
    }
  }, [toastMessage]);

  const downloadRationalisationPDF = (modalItem: any, type: 'merge' | 'decommission') => {
    if (!modalItem) return;
    const doc = new jsPDF();
    
    // Header Title
    doc.setFont("helvetica", "bold");
    doc.setFontSize(22);
    doc.setTextColor(15, 23, 42); // slate-900
    doc.text("BI Governance Rationalisation Report", 20, 25);
    
    // Subtitle & Date
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(100, 116, 139); // slate-500
    doc.text(`Generated: ${new Date().toLocaleDateString()} ${new Date().toLocaleTimeString()}`, 20, 33);
    doc.line(20, 36, 190, 36);
    
    let y = 48;
    
    const checkPageBreak = (neededHeight = 6) => {
      if (y + neededHeight > 270) {
        doc.addPage();
        y = 20;
      }
    };

    // Section 1: Recommendation Action
    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(30, 41, 59); // slate-800
    doc.text("1. Recommendation Action", 20, y);
    y += 8;
    
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(51, 65, 85); // slate-700
    doc.text(`Dashboard Name: ${modalItem.name || 'N/A'}`, 25, y);
    y += 8;

    checkPageBreak();
    if (type === 'decommission') {
      doc.text("We are decommissioning this dashboard.", 25, y);
      y += 12;
    } else {
      doc.text(`We are merging this dashboard. Target dashboard: ${modalItem.merge_with || 'N/A'}`, 25, y);
      y += 12;
    }
    
    // Section 2: Governance Rationale
    checkPageBreak(10);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(30, 41, 59);
    doc.text("2. Governance Rationale", 20, y);
    y += 8;
    
    doc.setFont("helvetica", "bold");
    doc.setFontSize(10);
    doc.setTextColor(30, 41, 59);
    doc.text("Reasons:", 25, y); y += 6;
    
    doc.setFont("helvetica", "normal");
    doc.setTextColor(51, 65, 85);
    const reasonsList = modalItem.reasons || [];
    if (reasonsList.length > 0) {
      reasonsList.forEach((r: string) => {
        checkPageBreak(6);
        doc.text(`- ${r}`, 28, y);
        y += 6;
      });
    } else {
      checkPageBreak(6);
      const defaultReason = type === 'merge' ? "- High semantic duplication with target dashboard" : "- Low usage activity and lack of active user base";
      doc.text(defaultReason, 28, y);
      y += 6;
    }
    y += 8;
    
    // Section 3: Affected Stakeholders
    checkPageBreak(12);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(30, 41, 59);
    doc.text("3. Affected User Groups", 20, y);
    y += 8;
    
    doc.setFont("helvetica", "normal");
    doc.setFontSize(10);
    doc.setTextColor(51, 65, 85);
    const groupsList = modalItem.user_groups || [];
    if (groupsList.length > 0) {
      checkPageBreak(6);
      doc.text(`Affected user groups: ${groupsList.join(', ')}`, 25, y);
    } else {
      checkPageBreak(6);
      doc.text("No active user groups are assigned as audience for this view.", 25, y);
    }
    y += 14;
    
    // Section 4: Mapped KPIs & Lineage
    checkPageBreak(12);
    doc.setFont("helvetica", "bold");
    doc.setFontSize(14);
    doc.setTextColor(30, 41, 59);
    doc.text("4. KPIs & Data Lineage Mapping", 20, y);
    y += 8;
    
    doc.setFont("helvetica", "bold");
    doc.setTextColor(30, 41, 59);
    doc.text("Resolved KPIs:", 25, y); y += 6;
    
    doc.setFont("helvetica", "normal");
    doc.setTextColor(51, 65, 85);
    const kpisList = modalItem.kpis || [];
    if (kpisList.length > 0) {
      kpisList.forEach((k: any) => {
        checkPageBreak(6);
        const kName = typeof k === 'string' ? k : (k.name || "Unnamed KPI");
        doc.text(`- ${kName}`, 28, y);
        y += 6;
      });
    } else {
      checkPageBreak(6);
      doc.text("No KPIs detected on this worksheet.", 28, y); y += 6;
    }
    
    y += 4;
    checkPageBreak(8);
    doc.setFont("helvetica", "bold");
    doc.setTextColor(30, 41, 59);
    doc.text("Source Tables Mapped in Lineage:", 25, y); y += 6;
    
    doc.setFont("helvetica", "normal");
    doc.setTextColor(51, 65, 85);
    const tablesList = modalItem.tables || [];
    if (tablesList.length > 0) {
      tablesList.forEach((t: string) => {
        checkPageBreak(6);
        doc.text(`- ${t}`, 28, y);
        y += 6;
      });
    } else {
      checkPageBreak(6);
      doc.text("No database tables mapped.", 28, y); y += 6;
    }
    
    doc.save(`BI_Rationalisation_Report_${modalItem.name.replace(/\s+/g, '_')}.pdf`);
  };

  // Helper to calculate Levenshtein distance
  const editDistance = (s1: string, s2: string): number => {
    s1 = s1.toLowerCase();
    s2 = s2.toLowerCase();
    const costs = [];
    for (let i = 0; i <= s1.length; i++) {
      let lastValue = i;
      for (let j = 0; j <= s2.length; j++) {
        if (i === 0) {
          costs[j] = j;
        } else {
          if (j > 0) {
            let newValue = costs[j - 1];
            if (s1.charAt(i - 1) !== s2.charAt(j - 1)) {
              newValue = Math.min(Math.min(newValue, lastValue), costs[j]) + 1;
            }
            costs[j - 1] = lastValue;
            lastValue = newValue;
          }
        }
      }
      if (i > 0) {
        costs[s2.length] = lastValue;
      }
    }
    return costs[s2.length];
  };

  // Helper to calculate similarity ratio
  const getSimilarity = (s1: string, s2: string): number => {
    let longer = s1;
    let shorter = s2;
    if (s1.length < s2.length) {
      longer = s2;
      shorter = s1;
    }
    const longerLength = longer.length;
    if (longerLength === 0) {
      return 1.0;
    }
    return (longerLength - editDistance(longer, shorter)) / longerLength;
  };

  // Helper to normalize spelling and abbreviations in KPI names
  const normalizeKpiName = (name: string): string => {
    let s = name.toLowerCase().trim();
    s = s.replace(/\bno\.?\s+of\b/g, "number of");
    s = s.replace(/\baccnt\s+exec\b/g, "account executive");
    s = s.replace(/\boppty\b/g, "opportunity");
    s = s.replace(/\bmeetings\b/g, "meeting");
    s = s.replace(/\binvoices\b/g, "invoice");
    s = s.replace(/\bavg\.?\b/g, "average");
    s = s.replace(/\bopportunities\b/g, "opportunity");
    s = s.replace(/\bbudget\b/g, "budget");
    return s.trim();
  };

  // Helper to get base metric by removing granularity
  const getBaseMetric = (kpiName: string) => {
    let s = normalizeKpiName(kpiName);
    let cleaned = s.replace(/\b(by|per)\b.*$/i, "").trim();
    cleaned = cleaned.replace(/\blevel\b/i, "").trim();
    cleaned = cleaned.replace(/\baging\b/i, "").trim();
    cleaned = cleaned.replace(/\b(variance from|rank of|percentage change in|total|change from previous year|year-over-year change in|% hit target for|claims|states|national|regions|region|state)\b/i, "").trim();
    cleaned = cleaned.replace(/\s+/g, " ");
    return cleaned.trim();
  };

  // Helper to check if KPI is shared between lists ignoring granularity
  const isKpiShared = (kpi: string, otherList?: string[]) => {
    if (!otherList || otherList.length === 0) return false;
    const kpiClean = normalizeKpiName(kpi);
    const base1 = getBaseMetric(kpi);
    if (!base1) return false;
    
    return otherList.some(other => {
      const otherClean = normalizeKpiName(other);
      if (kpiClean === otherClean) return true;
      
      const base2 = getBaseMetric(other);
      if (!base2) return false;
      if (base1 === base2) return true;
      
      // Topic overlap (highly specific terms)
      const topicWords = ['renewal', 'cross-sell', 'invoice', 'meeting', 'budget', 'claims', 'satisfaction', 'sales'];
      for (const word of topicWords) {
        if (kpiClean.includes(word) && otherClean.includes(word)) {
          return true;
        }
      }
      
      // SequenceMatcher ratio similarity
      const sim = getSimilarity(base1, base2);
      if (sim > 0.80) return true;
      
      return false;
    });
  };
  
  const fetchRecommendations = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await fetch(`${API_BASE_URL}/api/v1/agent/recommendations`);
      if (!res.ok) throw new Error('Failed to fetch recommendations');
      const json = await res.json();
      setData(json);
      onCacheData(json);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!cachedData) {
      fetchRecommendations();
    }
  }, [cachedData]);

  // Find the detail item of the matching merge candidate
  useEffect(() => {
    if (mergeModalItem && data) {
      const match = [...data.keep, ...data.merge, ...data.discard].find(
        d => d.name === mergeModalItem.merge_with
      );
      setMatchingItem(match || null);
    } else {
      setMatchingItem(null);
    }
  }, [mergeModalItem, data]);

  const [modalGraphData, setModalGraphData] = useState<{ nodes: any[]; links: any[] } | null>(null);
  const [loadingModalGraph, setLoadingModalGraph] = useState(false);

  useEffect(() => {
    if (mergeModalItem && matchingItem) {
      setLoadingModalGraph(true);
      setModalGraphData(null);
      
      const dashboardsQuery = `${mergeModalItem.name}|||${matchingItem.name}`;
      const timestamp = new Date().getTime();
      
      fetch(`${API_BASE_URL}/api/v1/kpi-graph/data?dashboards=${encodeURIComponent(dashboardsQuery)}&_t=${timestamp}`)
        .then(res => {
          if (!res.ok) throw new Error('Failed to fetch graph data');
          return res.json();
        })
        .then(data => {
          setModalGraphData(data);
        })
        .catch(err => {
          console.error("Error fetching modal graph data:", err);
        })
        .finally(() => {
          setLoadingModalGraph(false);
        });
    } else {
      setModalGraphData(null);
    }
  }, [mergeModalItem, matchingItem]);

  // Extract shared original KPI names from graph data
  const getSharedKpisFromGraph = (nodes: any[], links: any[]) => {
    const sharedKpiNames = new Set<string>();
    
    // 1. Find all KPI nodes
    const kpiNodes = nodes.filter(n => n.group === 'KPI');
    
    kpiNodes.forEach(kNode => {
      // 2. Count distinct dashboard connections
      const connectedDashboards = new Set<string>();
      links.forEach(l => {
        const srcId = typeof l.source === 'object' ? l.source.id : l.source;
        const tgtId = typeof l.target === 'object' ? l.target.id : l.target;
        
        if (srcId === kNode.id || tgtId === kNode.id) {
          const otherId = srcId === kNode.id ? tgtId : srcId;
          const otherNode = nodes.find(n => n.id === otherId);
          if (otherNode && otherNode.group === 'Dashboard') {
            connectedDashboards.add(otherNode.id);
          }
        }
      });
      
      // 3. If connected to both dashboards, add its original names
      if (connectedDashboards.size > 1) {
        if (kNode.original_names && Array.isArray(kNode.original_names)) {
          kNode.original_names.forEach((name: string) => sharedKpiNames.add(name));
        } else {
          // Fallback to label/core_metric
          sharedKpiNames.add(kNode.label);
        }
      }
    });
    
    return sharedKpiNames;
  };

  const sharedKpis = modalGraphData 
    ? getSharedKpisFromGraph(modalGraphData.nodes, modalGraphData.links)
    : new Set<string>();

  // Filter list by search term and selected workbook
  const filterList = (list: DashboardItem[]) => {
    return list.filter(item => {
      const matchesSearch = item.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
                            item.workbook_name.toLowerCase().includes(searchTerm.toLowerCase());
      const matchesWorkbook = selectedWorkbook === 'all' || item.workbook_name === selectedWorkbook;
      return matchesSearch && matchesWorkbook;
    });
  };

  if (loading) {
    return (
      <div className="flex flex-col items-center justify-center py-32 space-y-4">
        <Loader2 className="w-8 h-8 text-primary animate-spin" />
        <p className="text-sm text-muted-foreground">Analyzing BI repository metadata & calculating uniqueness...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-md mx-auto my-16 p-6 border border-red-500/20 bg-red-500/5 rounded-2xl text-center space-y-4">
        <AlertCircle className="w-10 h-10 text-red-500 mx-auto" />
        <h3 className="text-lg font-bold text-foreground">Recommendation Engine Error</h3>
        <p className="text-sm text-muted-foreground">{error}</p>
        <button 
          onClick={fetchRecommendations}
          className="px-4 py-2 bg-red-500 text-white rounded-lg text-sm font-medium hover:bg-red-600 transition-colors"
        >
          Try Again
        </button>
      </div>
    );
  }

  const workbooks = Array.from(new Set([
    ...(data?.keep.map(d => d.workbook_name) || []),
    ...(data?.merge.map(d => d.workbook_name) || []),
    ...(data?.discard.map(d => d.workbook_name) || [])
  ]));

  const filteredKeep = filterList(data?.keep || []);
  const filteredMerge = filterList(data?.merge || []);
  const filteredDiscard = filterList(data?.discard || []);

  const totalCount = filteredKeep.length + filteredMerge.length + filteredDiscard.length;

  return (
    <div className="space-y-6 animate-in fade-in zoom-in-95 duration-200">
      {/* Header with Active Rules Metrics */}
      <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-6 bg-card/20 border border-border/80 p-6 rounded-2xl">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <h2 className="text-3xl font-bold tracking-tight">Governance Recommendations</h2>
            <span className="text-[10px] font-bold uppercase tracking-wider text-blue-400 bg-blue-500/10 px-2 py-1 border border-blue-500/20 rounded-md flex items-center gap-1">
              <Sparkles className="w-3 h-3 text-blue-400" /> AI Driven
            </span>
          </div>
          <p className="text-sm text-muted-foreground max-w-xl">
            Our automated data steward analyzes dashboard usage, semantic overlaps, audience distribution, and access recency to enforce clean platform hygiene.
          </p>
        </div>
        
        {/* ACTIVE RULES METRICS */}
        <div className="border border-border bg-slate-950/40 rounded-xl p-4 lg:w-auto w-full min-w-[320px]">
          <p className="text-xs font-bold text-slate-400 uppercase tracking-wider mb-2.5">Active Rules Metrics</p>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-x-6 gap-y-2 text-[13px] text-slate-300">
            <div><span className="text-amber-400 font-bold">Merge:</span> same datasource, same audience, &amp; &gt;60% KPI overlap</div>
            <div><span className="text-rose-400 font-bold">Decommission:</span> last viewed &gt;180 d, 100% overlap, or empty audience</div>
            <div><span className="text-emerald-400 font-bold">Keep:</span> All other active dashboards</div>
          </div>
        </div>
      </div>

      {/* Filter Toolbar */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 bg-card p-4 rounded-xl border border-border">
        <div className="flex flex-col sm:flex-row items-center gap-3 flex-1 w-full">
          <div className="relative flex-1 w-full max-w-md">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <input
              type="text"
              placeholder="Search dashboard or workbook..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="w-full bg-transparent pl-9 pr-4 py-2 text-sm outline-none border border-border rounded-lg focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all"
            />
          </div>
          <select
            value={selectedWorkbook}
            onChange={(e) => setSelectedWorkbook(e.target.value)}
            className="w-full sm:w-64 bg-card border border-border rounded-lg px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary transition-all"
          >
            <option value="all">All Workbooks</option>
            {workbooks.map((wb, i) => (
              <option key={i} value={wb}>{wb}</option>
            ))}
          </select>
        </div>

        {/* Pills / Tabs on the right */}
        <div className="flex items-center gap-1.5 bg-slate-950/60 p-1 rounded-lg border border-border">
          <button
            onClick={() => setActiveTab('all')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all ${
              activeTab === 'all' 
                ? 'bg-slate-800 text-foreground' 
                : 'text-slate-400 hover:text-foreground'
            }`}
          >
            All Recommendations ({totalCount})
          </button>
          <button
            onClick={() => setActiveTab('merge')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 ${
              activeTab === 'merge' 
                ? 'bg-amber-500/10 text-amber-400 border border-amber-500/20' 
                : 'text-slate-400 hover:text-foreground border border-transparent'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
            Consolidate ({filteredMerge.length})
          </button>
          <button
            onClick={() => setActiveTab('discard')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 ${
              activeTab === 'discard' 
                ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20' 
                : 'text-slate-400 hover:text-foreground border border-transparent'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
            Decommission ({filteredDiscard.length})
          </button>
          <button
            onClick={() => setActiveTab('keep')}
            className={`px-3 py-1.5 rounded-md text-xs font-semibold transition-all flex items-center gap-1.5 ${
              activeTab === 'keep' 
                ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20' 
                : 'text-slate-400 hover:text-foreground border border-transparent'
            }`}
          >
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
            Keep ({filteredKeep.length})
          </button>
        </div>
      </div>

      {/* Lists in Parallel (Three Columns Grid) */}
      <div className={`grid gap-6 ${
        activeTab === 'all' 
          ? 'grid-cols-1 lg:grid-cols-3' 
          : 'grid-cols-1'
      }`}>
        
        {/* CONSOLIDATE COLUMN */}
        {(activeTab === 'all' || activeTab === 'merge') && (
          <div className="space-y-4 flex flex-col h-full">
            <div className="flex items-center justify-between pb-1">
              <h3 className="text-xs font-bold text-amber-500 uppercase tracking-wider flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-amber-500" /> CONSOLIDATE & MERGE
              </h3>
              <span className="text-[10px] font-bold text-amber-400 bg-amber-500/10 px-2.5 py-0.5 border border-amber-500/20 rounded-md">
                {filteredMerge.length} Redundant
              </span>
            </div>

            <div className="space-y-4 flex-1">
              {filteredMerge.map((item) => (
                <div key={item.id} className="bg-slate-900/60 backdrop-blur-md border border-slate-800/80 hover:border-amber-500/30 rounded-2xl p-5 transition-all flex flex-col gap-4 shadow-xl">
                  {/* Top Row */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-0.5 min-w-0 flex-1">
                      <h4 className="text-base font-bold text-foreground leading-snug break-words">{item.name}</h4>
                      <p className="text-xs text-slate-500 break-all">{item.workbook_name}</p>
                    </div>
                    <span className="text-xs font-bold shrink-0 text-amber-400 bg-amber-500/10 px-2.5 py-1 border border-amber-500/20 rounded-lg">
                      {Math.round(item.uniqueness * 100)}% Unique
                    </span>
                  </div>

                  {/* Metadata */}
                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5 text-slate-500" /> Viewed {item.days_ago}d ago
                    </span>
                    <span className="flex items-center gap-1 max-w-[150px] truncate">
                      <Users className="w-3.5 h-3.5 text-slate-500" /> {item.user_groups.join(', ') || 'None'}
                    </span>
                  </div>

                  {/* AI Summary */}
                  {item.summary && (
                    <div className="bg-slate-950/20 rounded-xl p-3 border border-slate-850/40 text-xs text-slate-400 italic leading-relaxed">
                      "{item.summary}"
                    </div>
                  )}

                  {/* Rationale Box */}
                  <div className="bg-slate-950/40 rounded-xl p-3 border border-slate-800/60">
                    <p className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-2">Governance Rationale</p>
                    <ul className="space-y-1.5">
                      {item.reasons.map((r, i) => (
                        <li key={i} className="text-xs text-slate-300 flex items-start gap-1.5 leading-relaxed">
                          <span className="text-amber-500 shrink-0 font-bold">!</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <OntologyScoreBadge inventory={item.ontology_inventory} />

                  {/* Common Connections Box */}
                  {(item.common_kpis?.length || item.common_tables?.length) && (
                    <div className="bg-amber-950/10 border border-amber-500/10 rounded-xl p-3 space-y-1.5">
                      <p className="text-[9px] font-bold text-amber-400 uppercase tracking-wider">Common Connections</p>
                      {item.common_kpis && item.common_kpis.length > 0 && (
                        <p className="text-xs text-slate-300">
                          <strong className="text-amber-400/95">Common KPIs:</strong> {item.common_kpis.join(', ')}
                        </p>
                      )}
                      {item.common_tables && item.common_tables.length > 0 && (
                        <p className="text-xs text-slate-300">
                          <strong className="text-amber-400/95">Common Datasources:</strong> {item.common_tables.join(', ')}
                        </p>
                      )}
                    </div>
                  )}

                  {/* Footer */}
                  <div className="flex items-center justify-between border-t border-slate-800/60 pt-3 mt-auto gap-2">
                    <span className="text-xs text-slate-500 max-w-[140px] truncate" title={`Merge into '${item.merge_with}'`}>
                      Merge into '{item.merge_with}'
                    </span>
                    <button 
                      onClick={() => setMergeModalItem(item)}
                      className="px-3.5 py-1.5 bg-amber-500 hover:bg-amber-600 text-slate-950 rounded-lg text-xs font-bold transition-all flex items-center gap-1 shadow-lg shadow-amber-500/15 cursor-pointer"
                    >
                      Review Merger <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}

              {filteredMerge.length === 0 && (
                <div className="text-center py-12 text-slate-500 bg-slate-950/20 border border-slate-800/50 rounded-2xl">
                  No merge recommendations.
                </div>
              )}
            </div>
          </div>
        )}

        {/* DECOMMISSION COLUMN */}
        {(activeTab === 'all' || activeTab === 'discard') && (
          <div className="space-y-4 flex flex-col h-full">
            <div className="flex items-center justify-between pb-1">
              <h3 className="text-xs font-bold text-rose-500 uppercase tracking-wider flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-rose-500" /> DECOMMISSION
              </h3>
              <span className="text-[10px] font-bold text-rose-400 bg-rose-500/10 px-2.5 py-0.5 border border-rose-500/20 rounded-md">
                {filteredDiscard.length} Inactive
              </span>
            </div>

            <div className="space-y-4 flex-1">
              {filteredDiscard.map((item) => (
                <div key={item.id} className="bg-slate-900/60 backdrop-blur-md border border-slate-800/80 hover:border-rose-500/30 rounded-2xl p-5 transition-all flex flex-col gap-4 shadow-xl">
                  {/* Top Row */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-0.5 min-w-0 flex-1">
                      <h4 className="text-base font-bold text-foreground leading-snug break-words">{item.name}</h4>
                      <p className="text-xs text-slate-500 break-all">{item.workbook_name}</p>
                    </div>
                    <span className="text-xs font-bold shrink-0 text-rose-400 bg-rose-500/10 px-2.5 py-1 border border-rose-500/20 rounded-lg">
                      {Math.round(item.uniqueness * 100)}% Unique
                    </span>
                  </div>

                  {/* Metadata */}
                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5 text-slate-500" /> Viewed {item.days_ago}d ago
                    </span>
                    <span className="flex items-center gap-1 max-w-[150px] truncate">
                      <Users className="w-3.5 h-3.5 text-slate-500" /> {item.user_groups.join(', ') || 'None'}
                    </span>
                  </div>

                  {/* AI Summary */}
                  {item.summary && (
                    <div className="bg-slate-950/20 rounded-xl p-3 border border-slate-850/40 text-xs text-slate-400 italic leading-relaxed">
                      "{item.summary}"
                    </div>
                  )}

                  {/* Rationale Box */}
                  <div className="bg-slate-950/40 rounded-xl p-3 border border-slate-800/60">
                    <p className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-2">Governance Rationale</p>
                    <ul className="space-y-1.5">
                      {item.reasons.map((r, i) => (
                        <li key={i} className="text-xs text-slate-300 flex items-start gap-1.5 leading-relaxed">
                          <span className="text-rose-500 shrink-0 font-bold">▲</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <OntologyScoreBadge inventory={item.ontology_inventory} />

                  {/* Footer */}
                  <div className="flex items-center justify-between border-t border-slate-800/60 pt-3 mt-auto">
                    <span className="text-xs text-slate-500 flex items-center gap-1">
                      <Database className="w-3.5 h-3.5" /> {item.tables.length} tables referenced
                    </span>
                    <button 
                      onClick={() => setDecommissionModalItem(item)}
                      className="px-3.5 py-1.5 bg-rose-500 hover:bg-rose-600 text-slate-950 rounded-lg text-xs font-bold transition-all flex items-center gap-1 shadow-lg shadow-rose-500/15 cursor-pointer"
                    >
                      Review Details <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              ))}

              {filteredDiscard.length === 0 && (
                <div className="text-center py-12 text-slate-500 bg-slate-950/20 border border-slate-800/50 rounded-2xl">
                  No decommission recommendations.
                </div>
              )}
            </div>
          </div>
        )}

        {/* KEEP COLUMN */}
        {(activeTab === 'all' || activeTab === 'keep') && (
          <div className="space-y-4 flex flex-col h-full">
            <div className="flex items-center justify-between pb-1">
              <h3 className="text-xs font-bold text-emerald-500 uppercase tracking-wider flex items-center gap-2">
                <span className="w-2 h-2 rounded-full bg-emerald-500" /> KEEP & CERTIFY
              </h3>
              <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-2.5 py-0.5 border border-emerald-500/20 rounded-md">
                {filteredKeep.length} Active
              </span>
            </div>
            
            <div className="space-y-4 flex-1">
              {filteredKeep.map((item) => (
                <div key={item.id} className="bg-slate-900/60 backdrop-blur-md border border-slate-800/80 hover:border-emerald-500/30 rounded-2xl p-5 transition-all flex flex-col gap-4 shadow-xl">
                  {/* Top Row */}
                  <div className="flex items-start justify-between gap-2">
                    <div className="space-y-0.5 min-w-0 flex-1">
                      <h4 className="text-base font-bold text-foreground leading-snug break-words">{item.name}</h4>
                      <p className="text-xs text-slate-500 break-all">{item.workbook_name}</p>
                    </div>
                    <span className="text-xs font-bold shrink-0 text-emerald-400 bg-emerald-500/10 px-2.5 py-1 border border-emerald-500/20 rounded-lg">
                      {Math.round(item.uniqueness * 100)}% Unique
                    </span>
                  </div>

                  {/* Metadata */}
                  <div className="flex items-center gap-4 text-xs text-slate-400">
                    <span className="flex items-center gap-1">
                      <Calendar className="w-3.5 h-3.5 text-slate-500" /> Viewed {item.days_ago}d ago
                    </span>
                    <span className="flex items-center gap-1 max-w-[150px] truncate">
                      <Users className="w-3.5 h-3.5 text-slate-500" /> {item.user_groups.join(', ') || 'None'}
                    </span>
                  </div>

                  {/* AI Summary */}
                  {item.summary && (
                    <div className="bg-slate-950/20 rounded-xl p-3 border border-slate-850/40 text-xs text-slate-400 italic leading-relaxed">
                      "{item.summary}"
                    </div>
                  )}

                  {/* Rationale Box */}
                  <div className="bg-slate-950/40 rounded-xl p-3 border border-slate-800/60">
                    <p className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-2">Governance Rationale</p>
                    <ul className="space-y-1.5">
                      {item.reasons.map((r, i) => (
                        <li key={i} className="text-xs text-slate-300 flex items-start gap-1.5 leading-relaxed">
                          <span className="text-emerald-500 shrink-0 font-bold">✓</span>
                          <span>{r}</span>
                        </li>
                      ))}
                    </ul>
                  </div>

                  <OntologyScoreBadge inventory={item.ontology_inventory} />

                  {/* Footer */}
                  <div className="flex items-center justify-between border-t border-slate-800/60 pt-3 mt-auto">
                    <span className="text-xs text-slate-500 flex items-center gap-1">
                      <Database className="w-3.5 h-3.5" /> {item.tables.length} tables referenced
                    </span>
                  </div>
                </div>
              ))}

              {filteredKeep.length === 0 && (
                <div className="text-center py-12 text-slate-500 bg-slate-950/20 border border-slate-800/50 rounded-2xl">
                  No keep recommendations.
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      {/* MERGER SIDE-BY-SIDE MODAL */}
      {mergeModalItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 overflow-y-auto animate-in fade-in duration-200">
          <div className="bg-background border border-border rounded-2xl shadow-2xl w-full max-w-5xl max-h-[95vh] flex flex-col overflow-hidden my-4">
            
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-amber-500/15 flex items-center justify-center">
                  <GitMerge className="w-5 h-5 text-amber-500" />
                </div>
                <div>
                  <h3 className="font-bold text-lg text-foreground">Consolidation Merger Review</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">Compare metrics, data sources, and target audiences side-by-side to review consolidating these views.</p>
                </div>
              </div>
              <button 
                onClick={() => setMergeModalItem(null)}
                className="p-1.5 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {/* Side-by-side comparison cards */}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                {/* Column 1: Source */}
                <div className="bg-slate-900/65 border border-slate-800 p-6 rounded-2xl space-y-5 flex flex-col">
                  <div className="border-b border-slate-800/80 pb-3 flex justify-between items-start gap-2">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-amber-500">Source View</span>
                      <h4 className="text-lg font-bold text-foreground mt-1 truncate">{mergeModalItem.name}</h4>
                      <p className="text-xs text-slate-500 mt-0.5 truncate">{mergeModalItem.workbook_name}</p>
                    </div>
                    <span className="text-[10px] font-semibold shrink-0 text-amber-400 bg-amber-500/10 px-2.5 py-0.5 border border-amber-500/20 rounded-md">
                      Viewed {mergeModalItem.days_ago}d ago
                    </span>
                  </div>

                  {/* Target Audience */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Audience Groups</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {mergeModalItem.user_groups.map((g, i) => (
                        <span key={i} className="text-xs px-2.5 py-1 bg-slate-950/40 border border-slate-850/80 text-slate-300 rounded-lg">
                          {g}
                        </span>
                      ))}
                      {mergeModalItem.user_groups.length === 0 && <span className="text-xs text-slate-500 italic">No audience assigned</span>}
                    </div>
                  </div>

                  {/* Database Tables */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Referenced Tables</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {mergeModalItem.tables.map((t, i) => {
                        const isCommon = matchingItem?.tables.some(t2 => t2.toLowerCase() === t.toLowerCase());
                        return (
                          <span 
                            key={i} 
                            className={`text-xs px-2.5 py-1 rounded-lg border transition-all ${
                              isCommon 
                                ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 font-medium' 
                                : 'bg-slate-950/40 text-slate-400 border-slate-800/80'
                            }`}
                          >
                            {t}
                          </span>
                        );
                      })}
                      {mergeModalItem.tables.length === 0 && <span className="text-xs text-slate-500 italic">No tables resolved</span>}
                    </div>
                  </div>

                  {/* Extracted KPIs */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Extracted KPIs</h5>
                    <div className="space-y-1.5 max-h-[220px] overflow-y-auto pr-1">
                      {(() => {
                        const getKpiCommonStatus = (kpiName: string) => {
                          return modalGraphData 
                            ? sharedKpis.has(kpiName)
                            : isKpiShared(kpiName, matchingItem?.kpis);
                        };
                        const sortedKpis = [...mergeModalItem.kpis].sort((a, b) => {
                          const aShared = getKpiCommonStatus(a);
                          const bShared = getKpiCommonStatus(b);
                          if (aShared && !bShared) return 1;  // shared goes below
                          if (!aShared && bShared) return -1; // non-shared goes above
                          return 0;
                        });
                        return sortedKpis.map((k, i) => {
                          const isCommon = getKpiCommonStatus(k);
                          return (
                            <div 
                              key={i} 
                              className={`p-2.5 rounded-lg flex items-center justify-between text-xs transition-all border ${
                                isCommon 
                                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 font-medium shadow-sm shadow-amber-500/5' 
                                  : 'bg-slate-950/30 border-slate-800/50 text-slate-300'
                              }`}
                            >
                              <span>{k}</span>
                              {isCommon && (
                                <span className="text-[9px] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 border border-amber-500/20 rounded shrink-0">
                                  SHARED
                                </span>
                              )}
                            </div>
                          );
                        });
                      })()}
                      {mergeModalItem.kpis.length === 0 && <span className="text-xs text-slate-500 italic">No KPIs resolved</span>}
                    </div>
                  </div>
                </div>

                {/* Column 2: Target */}
                <div className="bg-slate-900/65 border border-slate-800 p-6 rounded-2xl space-y-5 flex flex-col">
                  <div className="border-b border-slate-800/80 pb-3 flex justify-between items-start gap-2">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-500">Target Consolidate View</span>
                      <h4 className="text-lg font-bold text-foreground mt-1 truncate">{matchingItem?.name || mergeModalItem.merge_with}</h4>
                      <p className="text-xs text-slate-500 mt-0.5 truncate">{matchingItem?.workbook_name || 'resolving...'}</p>
                    </div>
                    {matchingItem && (
                      <span className="text-[10px] font-semibold shrink-0 text-emerald-400 bg-emerald-500/10 px-2.5 py-0.5 border border-emerald-500/20 rounded-md">
                        Viewed {matchingItem.days_ago}d ago
                      </span>
                    )}
                  </div>

                  {/* Target Audience */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Audience Groups</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {matchingItem?.user_groups.map((g, i) => (
                        <span key={i} className="text-xs px-2.5 py-1 bg-slate-950/40 border border-slate-850/80 text-slate-300 rounded-lg">
                          {g}
                        </span>
                      ))}
                      {(!matchingItem || matchingItem.user_groups.length === 0) && <span className="text-xs text-slate-500 italic">No audience assigned</span>}
                    </div>
                  </div>

                  {/* Database Tables */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Referenced Tables</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {matchingItem?.tables.map((t, i) => {
                        const isCommon = mergeModalItem.tables.some(t2 => t2.toLowerCase() === t.toLowerCase());
                        return (
                          <span 
                            key={i} 
                            className={`text-xs px-2.5 py-1 rounded-lg border transition-all ${
                              isCommon 
                                ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 font-medium' 
                                : 'bg-slate-950/40 text-slate-400 border-slate-800/80'
                            }`}
                          >
                            {t}
                          </span>
                        );
                      })}
                      {(!matchingItem || matchingItem.tables.length === 0) && <span className="text-xs text-slate-500 italic">No tables resolved</span>}
                    </div>
                  </div>

                  {/* Extracted KPIs */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Extracted KPIs</h5>
                    <div className="space-y-1.5 max-h-[220px] overflow-y-auto pr-1">
                      {matchingItem && (() => {
                        const getKpiCommonStatus = (kpiName: string) => {
                          return modalGraphData 
                            ? sharedKpis.has(kpiName)
                            : isKpiShared(kpiName, mergeModalItem.kpis);
                        };
                        const sortedKpis = [...matchingItem.kpis].sort((a, b) => {
                          const aShared = getKpiCommonStatus(a);
                          const bShared = getKpiCommonStatus(b);
                          if (aShared && !bShared) return 1;  // shared goes below
                          if (!aShared && bShared) return -1; // non-shared goes above
                          return 0;
                        });
                        return sortedKpis.map((k, i) => {
                          const isCommon = getKpiCommonStatus(k);
                          return (
                            <div 
                              key={i} 
                              className={`p-2.5 rounded-lg flex items-center justify-between text-xs transition-all border ${
                                isCommon 
                                  ? 'bg-amber-500/10 text-amber-400 border-amber-500/30 font-medium shadow-sm shadow-amber-500/5' 
                                  : 'bg-slate-950/30 border-slate-800/50 text-slate-300'
                              }`}
                            >
                              <span>{k}</span>
                              {isCommon && (
                                <span className="text-[9px] font-bold text-amber-400 bg-amber-500/10 px-2 py-0.5 border border-amber-500/20 rounded shrink-0">
                                  SHARED
                                </span>
                              )}
                            </div>
                          );
                        });
                      })()}
                      {(!matchingItem || matchingItem.kpis.length === 0) && <span className="text-xs text-slate-500 italic">No KPIs resolved</span>}
                    </div>
                  </div>
                </div>

              </div>

              {/* Lineage Graph highlighting common elements */}
              <div className="space-y-3 bg-slate-900/40 border border-slate-800 p-5 rounded-2xl">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-foreground uppercase tracking-wider flex items-center gap-1.5">
                      <TrendingUp className="w-4 h-4 text-amber-500" /> Visual Lineage & Common Connections Highlighted
                    </h4>
                    <p className="text-xs text-slate-400 mt-1">Showing connections for both dashboards. Shared KPIs and queried tables are outlined in amber.</p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0 sm:self-start">
                    <span className="text-[10px] font-semibold text-amber-400 bg-amber-500/10 border border-amber-500/20 px-2.5 py-0.5 rounded-lg shrink-0">
                      Common KPIs and Tables are Highlighted
                    </span>
                  </div>
                </div>
                <div className="bg-slate-950 border border-slate-800/80 rounded-xl h-[380px] overflow-hidden relative mt-2 p-3">
                  <KPIDashboardGraph 
                    dashboards={`${mergeModalItem.name}|||${mergeModalItem.merge_with}`} 
                    height="290px" 
                    graphData={modalGraphData}
                  />
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-slate-800 bg-slate-900/60 shrink-0">
              <div className="flex items-center gap-2 text-xs font-semibold text-amber-400">
                <TrendingUp className="w-4 h-4 text-amber-500" />
                <span>Consolidating saves 1 redundant server extract refresh schedule</span>
              </div>
              <div className="flex items-center gap-3">
                <button 
                  onClick={() => setMergeModalItem(null)}
                  className="px-4 py-2 border border-slate-800 hover:bg-slate-800 rounded-lg text-sm font-semibold transition-colors"
                >
                  Cancel
                </button>
                <button 
                  onClick={() => {
                    setEmailDraft({
                      to: 'governance-team@company.com',
                      subject: 'BI Rationalisation Recommendation',
                      body: `Dear Team,\n\nBased on the Rationalisation exercise, the dashboard '${mergeModalItem.name}' from report '${mergeModalItem.workbook_name}' is recommended to be merged into '${mergeModalItem.merge_with}' to reduce semantic duplication.\n\nRationale:\n${mergeModalItem.reasons?.map((r: string) => `- ${r}`).join('\n') || '- Semantic redundancy'}\n\nFor further details please refer to the attached pdf.\n\nBest regards,\nBI Governance Steward`,
                      type: 'merge'
                    });
                  }}
                  className="px-4 py-2 bg-amber-500 hover:bg-amber-600 text-slate-950 rounded-lg text-sm font-bold transition-colors shadow-lg shadow-amber-500/15 cursor-pointer"
                >
                  Apply Merger
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* DECOMMISSION REVIEW MODAL */}
      {decommissionModalItem && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 overflow-y-auto animate-in fade-in duration-200">
          <div className="bg-background border border-border rounded-2xl shadow-2xl w-full max-w-5xl max-h-[95vh] flex flex-col overflow-hidden my-4">
            
            {/* Header */}
            <div className="flex items-center justify-between px-6 py-4 border-b border-border shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-xl bg-rose-500/15 flex items-center justify-center">
                  <Trash2 className="w-5 h-5 text-rose-500" />
                </div>
                <div>
                  <h3 className="font-bold text-lg text-foreground">Decommission Governance Review</h3>
                  <p className="text-xs text-muted-foreground mt-0.5">Review user groups, referenced tables, KPIs, and lineage connections before decommissioning this view.</p>
                </div>
              </div>
              <button 
                onClick={() => setDecommissionModalItem(null)}
                className="p-1.5 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            {/* Content */}
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                
                {/* Dashboard Details */}
                <div className="bg-slate-900/65 border border-slate-800 p-6 rounded-2xl space-y-5 flex flex-col">
                  <div className="border-b border-slate-800/80 pb-3 flex justify-between items-start gap-2">
                    <div>
                      <span className="text-[10px] font-bold uppercase tracking-wider text-rose-500">Decommission Candidate</span>
                      <h4 className="text-lg font-bold text-foreground mt-1 break-words">{decommissionModalItem.name}</h4>
                      <p className="text-xs text-slate-500 mt-0.5 break-all">{decommissionModalItem.workbook_name}</p>
                    </div>
                    <span className="text-[10px] font-semibold shrink-0 text-rose-400 bg-rose-500/10 px-2.5 py-0.5 border border-rose-500/20 rounded-md">
                      Viewed {decommissionModalItem.days_ago}d ago
                    </span>
                  </div>

                  {/* Target Audience */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Audience Groups</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {decommissionModalItem.user_groups.map((g, i) => (
                        <span key={i} className="text-xs px-2.5 py-1 bg-slate-950/40 border border-slate-850/80 text-slate-300 rounded-lg">
                          {g}
                        </span>
                      ))}
                      {decommissionModalItem.user_groups.length === 0 && <span className="text-xs text-slate-500 italic">No audience assigned</span>}
                    </div>
                  </div>

                  {/* Database Tables */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Referenced Tables</h5>
                    <div className="flex flex-wrap gap-1.5">
                      {decommissionModalItem.tables.map((t, i) => (
                        <span key={i} className="text-xs px-2.5 py-1 bg-slate-950/40 text-slate-400 border border-slate-800/80 rounded-lg">
                          {t}
                        </span>
                      ))}
                      {decommissionModalItem.tables.length === 0 && <span className="text-xs text-slate-500 italic">No tables resolved</span>}
                    </div>
                  </div>

                  {/* Extracted KPIs */}
                  <div className="space-y-2">
                    <h5 className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Extracted KPIs</h5>
                    <div className="space-y-1.5 max-h-[220px] overflow-y-auto pr-1">
                      {decommissionModalItem.kpis.map((k, i) => (
                        <div key={i} className="bg-slate-950/30 border border-slate-800/50 p-2.5 rounded-lg text-xs text-slate-300">
                          {k}
                        </div>
                      ))}
                      {decommissionModalItem.kpis.length === 0 && <span className="text-xs text-slate-500 italic">No KPIs resolved</span>}
                    </div>
                  </div>
                </div>

                {/* Governance Rationale & Info */}
                <div className="bg-slate-900/65 border border-slate-800 p-6 rounded-2xl space-y-5 flex flex-col justify-between">
                  <div className="space-y-5">
                    <div className="border-b border-slate-800/80 pb-3">
                      <span className="text-[10px] font-bold uppercase tracking-wider text-rose-500">Governance Rationale</span>
                      <h4 className="text-sm font-semibold text-slate-300 mt-2">Why Decommission?</h4>
                    </div>

                    {decommissionModalItem.summary && (
                      <div className="bg-slate-950/40 rounded-xl p-4 border border-slate-800/60 space-y-1.5">
                        <p className="text-[9px] font-bold text-slate-500 uppercase tracking-wider">Dashboard Summary</p>
                        <p className="text-xs text-slate-300 leading-relaxed italic">"{decommissionModalItem.summary}"</p>
                      </div>
                    )}

                    <div className="bg-slate-950/40 rounded-xl p-4 border border-slate-800/60">
                      <p className="text-[9px] font-bold text-slate-500 uppercase tracking-wider mb-2">Platform Cleanliness Violations</p>
                      <ul className="space-y-2">
                        {decommissionModalItem.reasons.map((r, i) => (
                          <li key={i} className="text-xs text-slate-300 flex items-start gap-2 leading-relaxed">
                            <span className="text-rose-500 shrink-0 font-bold">▲</span>
                            <span>{r}</span>
                          </li>
                        ))}
                      </ul>
                    </div>

                    <div className="bg-rose-950/10 border border-rose-500/10 rounded-xl p-4 text-xs text-rose-300 leading-relaxed">
                      <strong>Governance Impact Alert:</strong> This action will notify all active subscribers, disconnect the datasource connections, and archive the metadata in the repository index.
                    </div>
                  </div>
                </div>

              </div>

              {/* Lineage Graph */}
              <div className="space-y-3 bg-slate-900/40 border border-slate-800 p-5 rounded-2xl">
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div>
                    <h4 className="text-sm font-bold text-foreground uppercase tracking-wider flex items-center gap-1.5">
                      <TrendingUp className="w-4 h-4 text-rose-500" /> Dashboard Connections Lineage
                    </h4>
                    <p className="text-xs text-slate-400 mt-1">Showing active data lineage mapping for the decommission candidate.</p>
                  </div>
                </div>
                <div className="bg-slate-950 border border-slate-800/80 rounded-xl h-[380px] overflow-hidden relative mt-2 p-3">
                  <KPIDashboardGraph dashboards={decommissionModalItem.name} height="290px" />
                </div>
              </div>
            </div>

            {/* Footer */}
            <div className="flex items-center justify-between px-6 py-4 border-t border-slate-800 bg-slate-900/60 shrink-0">
              <span className="text-xs font-semibold text-rose-400">
                Archiving this view frees database execution threads and server space
              </span>
              <div className="flex items-center gap-3">
                <button 
                  onClick={() => setDecommissionModalItem(null)}
                  className="px-4 py-2 border border-slate-800 hover:bg-slate-800 rounded-lg text-sm font-semibold transition-colors"
                >
                  Cancel
                </button>
                <button 
                  onClick={() => {
                    setEmailDraft({
                      to: 'governance-team@company.com',
                      subject: 'BI Rationalisation Recommendation',
                      body: `Dear Team,\n\nBased on the Rationalisation exercise, the dashboard '${decommissionModalItem.name}' from report '${decommissionModalItem.workbook_name}' is recommended to be decommissioned.\n\nRationale:\n${decommissionModalItem.reasons?.map((r: string) => `- ${r}`).join('\n') || '- Inactivity or redundant content'}\n\nFor further details please refer to the attached pdf.\n\nBest regards,\nBI Governance Steward`,
                      type: 'decommission'
                    });
                  }}
                  className="px-4 py-2 bg-rose-500 hover:bg-rose-600 text-slate-950 rounded-lg text-sm font-bold transition-colors shadow-lg shadow-rose-500/15"
                >
                  Apply Decommission
                </button>
              </div>
            </div>

          </div>
        </div>
      )}



      {/* EMAIL NOTIFICATION MODAL */}
      {emailDraft && (
        <div className="fixed inset-0 z-[150] flex items-center justify-center bg-black/85 backdrop-blur-md p-4 animate-in fade-in duration-200">
          <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-2xl flex flex-col overflow-hidden shadow-2xl relative">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-950/40 shrink-0">
              <h3 className="font-bold text-base text-foreground flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-blue-400" /> BI Rationalisation Recommendation Email
              </h3>
              <button 
                onClick={() => setEmailDraft(null)}
                className="p-1 hover:bg-slate-800 rounded-lg text-slate-400 hover:text-foreground transition-colors cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            
            <div className="p-6 space-y-4">
              <div className="space-y-1">
                <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">To</label>
                <input 
                  type="text" 
                  value={emailDraft.to}
                  onChange={(e) => setEmailDraft({ ...emailDraft, to: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-blue-500 transition-colors"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Subject</label>
                <input 
                  type="text" 
                  value={emailDraft.subject}
                  onChange={(e) => setEmailDraft({ ...emailDraft, subject: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-sm text-foreground outline-none focus:border-blue-500 transition-colors"
                />
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-bold text-slate-500 uppercase tracking-wider">Body</label>
                <textarea 
                  rows={10}
                  value={emailDraft.body}
                  onChange={(e) => setEmailDraft({ ...emailDraft, body: e.target.value })}
                  className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs text-foreground outline-none focus:border-blue-500 transition-colors font-mono resize-none leading-relaxed"
                />
              </div>
            </div>

            <div className="flex items-center justify-between px-6 py-4 border-t border-slate-800 bg-slate-950/20 shrink-0">
              <button 
                onClick={() => downloadRationalisationPDF(emailDraft.type === 'merge' ? mergeModalItem : decommissionModalItem, emailDraft.type)}
                className="flex items-center gap-2 px-3 py-2 bg-slate-850 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-blue-400 hover:text-blue-300 rounded-lg text-xs font-semibold transition-colors cursor-pointer"
              >
                <FileDown className="w-3.5 h-3.5" /> Download Attached PDF
              </button>
              <div className="flex items-center gap-3">
                <button 
                  onClick={() => setEmailDraft(null)}
                  className="px-4 py-2 border border-slate-800 hover:bg-slate-800 rounded-lg text-sm font-semibold transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button 
                  onClick={() => {
                    setToastMessage(emailDraft.type === 'merge' ? "Merger email notification successfully sent!" : "Decommission email notice sent to team!");
                    setEmailDraft(null);
                    setMergeModalItem(null);
                    setDecommissionModalItem(null);
                  }}
                  className="px-5 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-bold transition-all shadow-lg shadow-blue-950/50 cursor-pointer"
                >
                  Send Email
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* TOAST SUCCESS ALERT */}
      {toastMessage && (
        <div className="fixed top-6 right-6 z-[200] bg-emerald-500 text-slate-950 px-5 py-3 rounded-xl font-bold flex items-center gap-2 shadow-2xl animate-in slide-in-from-top-5 duration-300">
          <span className="w-2 h-2 rounded-full bg-slate-950 animate-ping" />
          {toastMessage}
        </div>
      )}
    </div>
  );
}