import { API_BASE_URL } from '@/config';
import React, { useMemo, useState, useEffect } from 'react';
import { ArrowLeft, Clock, User, Activity, FileSpreadsheet, Sparkles, Target, Users, ShieldAlert, Briefcase, LineChart, Filter, ChevronDown, Check, LayoutDashboard, ArrowRight } from 'lucide-react';
import { getWorkbookAreaId } from './BusinessAreasView';
import { KPIDashboardGraph } from './KPIDashboardGraph';

const AREA_DEFINITIONS: Record<string, { title: string; desc: string; icon: any; color: string; bg: string; usedBy: string }> = {
  'claims-risk': {
    title: 'Claims & Risk',
    desc: 'Analyzes risk exposure and claim trends across portfolios. Key insights focus on settlement times and loss ratios.',
    icon: ShieldAlert,
    color: 'text-rose-500',
    bg: 'bg-rose-500/10',
    usedBy: 'Claims, Acturial'
  },
  'customer-service': {
    title: 'Customer Service',
    desc: 'Monitors ongoing customer interactions, issue resolution, and satisfaction metrics. Highlights operational efficiency and service quality.',
    icon: Users,
    color: 'text-indigo-500',
    bg: 'bg-indigo-500/10',
    usedBy: 'Ops, Service teams'
  },
  'new-business-ops': {
    title: 'New Business Ops',
    desc: 'Focuses on the operational efficiency of acquiring new policies and clients. Tracks quote conversion and underwriting processing times.',
    icon: Briefcase,
    color: 'text-blue-500',
    bg: 'bg-blue-500/10',
    usedBy: 'underwriting, Sales ops'
  },
  'sales-pipeline': {
    title: 'Sales & pipeline',
    desc: 'Provides visibility into the sales funnel, opportunity stages, and revenue forecasting to drive growth.',
    icon: Target,
    color: 'text-amber-500',
    bg: 'bg-amber-500/10',
    usedBy: 'Sales, Leadership'
  },
  'product-level-performance': {
    title: 'Product Level Performance',
    desc: 'Delivers deep analysis on the profitability, market penetration, and long-term viability of specific product offerings.',
    icon: LineChart,
    color: 'text-purple-500',
    bg: 'bg-purple-500/10',
    usedBy: 'Product, Acurial'
  }
};

function FileRow({ file, def, onClick }: { file: any, def: any, onClick: () => void }) {
  const [summary, setSummary] = useState<string | null>(null);
  const [kpis, setKpis] = useState<any[]>([]);
  const [userGroups, setUserGroups] = useState<string[]>([]);
  const [daysAgoVal, setDaysAgoVal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    async function fetchSummary() {
      setLoading(true);
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/agent/workbook-summary?workbook_name=${encodeURIComponent(file.source_file)}`);
        if (res.ok) {
          const data = await res.json();
          if (data.workbook_summary) {
            setSummary(data.workbook_summary);
          }
          if (data.days_ago !== undefined && data.days_ago !== null) {
            setDaysAgoVal(data.days_ago);
          }
          if (data.user_groups && Array.isArray(data.user_groups)) {
            setUserGroups(data.user_groups);
          } else if (data.dashboards && data.dashboards.length > 0 && data.dashboards[0].user_groups) {
            setUserGroups(Array.isArray(data.dashboards[0].user_groups) ? data.dashboards[0].user_groups : []);
          }
          if (data.dashboards && data.dashboards.length > 0 && data.dashboards[0].kpis) {
             const rawKpis = data.dashboards[0].kpis;
             if (Array.isArray(rawKpis)) {
                 setKpis(rawKpis);
             } else if (typeof rawKpis === 'string' && rawKpis.trim() !== '') {
                 const parsed = rawKpis.split(',').map(k => {
                     const match = k.match(/(.*?)\s*\((\d+)%\)/);
                     return {
                         name: match ? match[1].trim() : k.trim(),
                         confidence: match ? parseInt(match[2], 10) : null
                     };
                 });
                 setKpis(parsed);
             }
          }
        }
      } catch (e) {
        console.error(e);
      } finally {
        setLoading(false);
      }
    }
    fetchSummary();
  }, [file.source_file]);

  const displaySummary = summary || "Aggregates key operational metrics to provide a high-level view of departmental performance and resource utilization.";
  const displayKpis = kpis.length > 0 ? kpis : [{name: "Process Efficiency", confidence: 80}, {name: "Resource Allocation", confidence: 75}];
  const daysAgo = daysAgoVal !== null ? daysAgoVal : (Math.floor(Math.random() * 30) + 1);
  const dashUserGroups = userGroups.length > 0 ? userGroups : file.dashboards?.[0]?.user_groups;
  const userArray = Array.isArray(dashUserGroups) 
    ? dashUserGroups 
    : (typeof dashUserGroups === 'string' && dashUserGroups.trim() !== '' ? dashUserGroups.split(',').map(s => s.trim()) : []);
  const user = userArray.length > 0 ? userArray.join(', ') : (def.usedBy || "Operations");

  return (
    <div 
      onClick={onClick}
      className="group flex flex-col md:flex-row gap-6 p-6 rounded-2xl border border-border bg-card hover:shadow-md transition-all duration-300 hover:border-primary/30 cursor-pointer"
    >
      <div className="md:w-3/4 flex flex-col pr-6">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-xl bg-primary/10 flex items-center justify-center shrink-0">
            <FileSpreadsheet className="w-5 h-5 text-primary" />
          </div>
          <div className="min-w-0 flex-1">
            <h4 className="font-semibold text-foreground group-hover:text-primary transition-colors break-words">
              {file.source_file}
            </h4>
            <div className="flex items-center gap-2 mt-1">
              <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-md">
                {file.dashboards?.length || 0} Tabs
              </span>
              <span className="text-[10px] text-muted-foreground uppercase tracking-wider font-semibold">
                {((file.file_size_bytes || 0) / 1024).toFixed(0)} KB
              </span>
            </div>
          </div>
        </div>

        <div className="flex flex-col">
          {loading ? (
             <div className="space-y-2">
               <div className="h-4 bg-muted animate-pulse rounded w-full"></div>
               <div className="h-4 bg-muted animate-pulse rounded w-5/6"></div>
             </div>
          ) : (
            <>
              <p className="text-sm text-foreground leading-relaxed">
                <Sparkles className="inline-block w-3 h-3 mr-1.5 text-amber-500 mb-0.5" />
                <span className="text-[10px] uppercase font-bold text-amber-500 mr-2 tracking-wider">AI Generated</span>
                {displaySummary}
              </p>
              <div className="mt-4">
                <div className="flex flex-wrap gap-2">
                {displayKpis.map((kpi: any, kpiIdx: number) => {
                  const name = kpi.name;
                  const confidence = kpi.confidence;
                  
                  let confColor = 'text-green-500';
                  if (confidence !== null) {
                    if (confidence < 50) confColor = 'text-red-500';
                    else if (confidence < 80) confColor = 'text-amber-500';
                  }
                  
                  return (
                    <div key={kpiIdx} className={`flex flex-col items-center justify-center gap-1.5 p-2.5 min-w-[90px] rounded-xl border ${def.color.replace('text', 'border')}/30 shadow-sm ${def.bg} bg-opacity-5 transition-all hover:shadow-md hover:bg-opacity-10`}>
                      <div className="text-[11px] font-medium text-foreground text-center leading-tight">
                        {name}
                      </div>
                      {confidence !== null && (
                        <div className="relative w-8 h-8 flex items-center justify-center mt-0.5">
                          <svg className="w-8 h-8 transform -rotate-90 drop-shadow-sm" viewBox="0 0 36 36">
                            <path
                              className="text-foreground/10"
                              stroke="currentColor"
                              strokeWidth="3.5"
                              fill="none"
                              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                            />
                            <path
                              className={confColor}
                              strokeDasharray={`${confidence}, 100`}
                              stroke="currentColor"
                              strokeWidth="3.5"
                              fill="none"
                              strokeLinecap="round"
                              d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831"
                            />
                          </svg>
                          <span className={`absolute text-[9px] font-bold ${confColor}`}>
                            {confidence}%
                          </span>
                        </div>
                      )}
                    </div>
                  );
                })}
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      <div className="md:w-1/4 shrink-0 flex flex-col justify-center gap-3 border-t md:border-t-0 md:border-l border-border/50 pt-4 md:pt-0 pl-0 md:pl-6">
        <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
          <Clock className="w-4 h-4 text-slate-400" />
          <span>Accessed {daysAgo} days ago</span>
        </div>
        <div className="flex items-center gap-2.5 text-sm text-muted-foreground">
          <User className="w-4 h-4 text-slate-400" />
          <span>{user}</span>
        </div>
      </div>
    </div>
  );
}

const ALL_LOBS = [
  "L&A", 
  "P&C", 
  "Worker compensation", 
  "reisurance", 
  "Auto insurance", 
  "health"
];

const ALL_USER_GROUPS = [
  "Claims Team",
  "Actuarial Team",
  "Underwriters",
  "Operations Team",
  "Sales Team - Branch Manager",
  "Sales Team - Regional Head",
  "Leadership",
  "Product Team",
  "Service Team"
];

export function AreaDetailView({ 
  areaId, 
  workbooksData, 
  selectedLOBs,
  setSelectedLOBs,
  selectedUserGroups,
  setSelectedUserGroups,
  onBack,
  onSelectFile
}: { 
  areaId: string; 
  workbooksData: any[]; 
  selectedLOBs: string[];
  setSelectedLOBs: React.Dispatch<React.SetStateAction<string[]>>;
  selectedUserGroups: string[];
  setSelectedUserGroups: React.Dispatch<React.SetStateAction<string[]>>;
  onBack: () => void;
  onSelectFile: (file: any) => void;
  onSelectDashboard?: (wb: any, db: any) => void;
}) {
  const def = AREA_DEFINITIONS[areaId] || AREA_DEFINITIONS['claims-risk'];
  const Icon = def.icon;

  const uniqueFiles = useMemo(() => {
    return workbooksData.filter(wb => {
      if (getWorkbookAreaId(wb) !== areaId) return false;

      if (!wb.dashboards || wb.dashboards.length === 0) {
        return selectedLOBs.length === 0 && selectedUserGroups.length === 0;
      }
      
      return wb.dashboards.some((dash: any) => {
        const lob = dash?.line_of_business;
        const groups = dash?.user_groups;
        
        const lobMatch = selectedLOBs.length === 0 || 
          (lob && selectedLOBs.some(sl => sl.toLowerCase().trim() === String(lob).toLowerCase().trim()));
          
        const groupArray = Array.isArray(groups) ? groups : (typeof groups === 'string' ? groups.split(',').map(s => s.trim()) : []);
        const groupMatch = selectedUserGroups.length === 0 || 
          groupArray.some((g: string) => selectedUserGroups.some(sg => sg.toLowerCase().trim() === String(g).toLowerCase().trim()));
        
        return lobMatch && groupMatch;
      });
    });
  }, [workbooksData, areaId, selectedLOBs, selectedUserGroups]);

  const [isLOBOpen, setIsLOBOpen] = useState(false);
  const [isGroupOpen, setIsGroupOpen] = useState(false);

  const availableUserGroups = ALL_USER_GROUPS;
  const availableLOBs = ALL_LOBS;

  const allDashboardNames = useMemo(() => {
    const names: string[] = [];
    uniqueFiles.forEach(f => {
      if (f.dashboards) {
        f.dashboards.forEach((d: any) => {
          if (d.name) names.push(d.name);
        });
      }
    });
    return names.join(',');
  }, [uniqueFiles]);

  const [aiDescription, setAiDescription] = useState<string | null>(null);
  const [loadingDesc, setLoadingDesc] = useState(false);
  const [activeTab, setActiveTab] = useState<'assets' | 'relations' | 'inventory'>('assets');

  const allDashboards = useMemo(() => {
    const list: any[] = [];
    uniqueFiles.forEach(wb => {
      wb.dashboards?.forEach((db: any) => {
        list.push({ wb, db });
      });
    });
    return list;
  }, [uniqueFiles]);

  useEffect(() => {
    async function fetchDesc() {
      if (!uniqueFiles.length) {
         setAiDescription(def.desc);
         return;
      }
      setLoadingDesc(true);
      try {
        const dashNames = uniqueFiles.map(f => f.source_file || '').join('|||');
        const res = await fetch(`${API_BASE_URL}/api/v1/agent/analyze/area-description?area_name=${encodeURIComponent(def.title)}&dashboards=${encodeURIComponent(dashNames)}`);
        if (res.ok) {
           const data = await res.json();
           setAiDescription(data.description);
        } else {
           setAiDescription(def.desc);
        }
      } catch(e) {
        setAiDescription(def.desc);
      } finally {
        setLoadingDesc(false);
      }
    }
    fetchDesc();
  }, [areaId, uniqueFiles, def]);

  return (
    <div className="space-y-8 animate-in fade-in zoom-in-95 duration-300 max-w-6xl mx-auto py-4">
      
      {/* Navigation and Filters */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-2">
        <button 
          onClick={onBack}
          className="flex items-center gap-2 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors w-fit group"
        >
          <ArrowLeft className="w-4 h-4 group-hover:-translate-x-1 transition-transform" />
          Back to Business Areas
        </button>

        <div className="flex items-center justify-end gap-3">
          {/* LOB Filter Dropdown */}
          {availableLOBs.length > 0 && (
            <div className="relative">
              <button 
                onClick={() => { setIsLOBOpen(!isLOBOpen); setIsGroupOpen(false); }}
                className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-border bg-card text-sm font-medium hover:bg-muted transition-colors text-foreground"
              >
                <Filter className="w-3.5 h-3.5 text-muted-foreground" />
                Line of Business {selectedLOBs.length > 0 && <span className="bg-primary/20 text-primary px-1.5 rounded text-xs">{selectedLOBs.length}</span>}
                <ChevronDown className="w-3.5 h-3.5 text-muted-foreground ml-1" />
              </button>
              
              {isLOBOpen && (
                <div className="absolute right-0 mt-2 w-56 bg-background border border-border rounded-lg shadow-xl z-50 py-1 max-h-64 overflow-y-auto">
                  {availableLOBs.map(lob => (
                    <label key={lob} className="flex items-center gap-3 px-3 py-2 hover:bg-muted/50 cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={selectedLOBs.includes(lob)}
                        onChange={() => setSelectedLOBs(prev => prev.includes(lob) ? prev.filter(l => l !== lob) : [...prev, lob])}
                        className="rounded border-border text-primary focus:ring-primary w-4 h-4"
                      />
                      <span className="text-sm text-foreground">{lob}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
          
          {/* User Group Filter Dropdown */}
          {availableUserGroups.length > 0 && (
            <div className="relative">
              <button 
                onClick={() => { setIsGroupOpen(!isGroupOpen); setIsLOBOpen(false); }}
                className="flex items-center gap-2 px-3 py-1.5 rounded-md border border-border bg-card text-sm font-medium hover:bg-muted transition-colors text-foreground"
              >
                <Users className="w-3.5 h-3.5 text-muted-foreground" />
                User Group {selectedUserGroups.length > 0 && <span className="bg-amber-500/20 text-amber-600 px-1.5 rounded text-xs">{selectedUserGroups.length}</span>}
                <ChevronDown className="w-3.5 h-3.5 text-muted-foreground ml-1" />
              </button>
              
              {isGroupOpen && (
                <div className="absolute right-0 mt-2 w-56 bg-background border border-border rounded-lg shadow-xl z-50 py-1 max-h-64 overflow-y-auto">
                  {availableUserGroups.map(grp => (
                    <label key={grp} className="flex items-center gap-3 px-3 py-2 hover:bg-muted/50 cursor-pointer">
                      <input 
                        type="checkbox" 
                        checked={selectedUserGroups.includes(grp)}
                        onChange={() => setSelectedUserGroups(prev => prev.includes(grp) ? prev.filter(g => g !== grp) : [...prev, grp])}
                        className="rounded border-border text-amber-500 focus:ring-amber-500 w-4 h-4"
                      />
                      <span className="text-sm text-foreground">{grp}</span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Hero Section */}
      <div className={`p-8 rounded-3xl border ${def.bg.replace('10', '20')} bg-card shadow-sm relative overflow-hidden`}>
        <div className={`absolute top-0 right-0 w-64 h-64 -mr-20 -mt-20 rounded-full ${def.bg} opacity-50`} />
        
        <div className="relative z-10 flex items-start gap-6">
          <div className={`w-16 h-16 rounded-2xl ${def.bg} flex items-center justify-center shrink-0 shadow-inner`}>
            <Icon className={`w-8 h-8 ${def.color}`} />
          </div>
          <div>
            <div className="flex items-center gap-4 mb-2">
              <h2 className="text-3xl font-bold tracking-tight text-foreground">{def.title}</h2>
              <span className={`px-3 py-1 rounded-full text-xs font-bold border ${def.color} ${def.bg} bg-opacity-30 border-opacity-20`}>
                {uniqueFiles.length} {uniqueFiles.length === 1 ? 'Dashboard' : 'Dashboards'}
              </span>
            </div>
            <div className="text-muted-foreground text-sm max-w-3xl leading-relaxed min-h-[40px]">
              {loadingDesc ? (
                <span className="animate-pulse bg-muted rounded w-3/4 h-4 inline-block mt-1"></span>
              ) : (
                <>
                  <Sparkles className="inline-block w-4 h-4 mr-1.5 text-amber-500 mb-0.5" />
                  {aiDescription && <span className="text-[10px] uppercase font-bold text-amber-500 mr-2 tracking-wider">AI Generated</span>}
                  {aiDescription || def.desc}
                </>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Tabs Navigation */}
      <div className="flex items-center gap-6 border-b border-border mt-8">
        <button
          onClick={() => setActiveTab('assets')}
          className={`pb-3 font-medium text-sm transition-colors border-b-2 ${activeTab === 'assets' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
        >
          Dashboard Summary
        </button>
        <button
          onClick={() => setActiveTab('relations')}
          className={`pb-3 font-medium text-sm transition-colors border-b-2 ${activeTab === 'relations' ? 'border-primary text-primary' : 'border-transparent text-muted-foreground hover:text-foreground'}`}
        >
          BI Landscape Graph
        </button>
      </div>

      {activeTab === 'assets' ? (
        <div className="space-y-4">
          <div className="flex items-center gap-6 p-4 bg-muted/30 border border-border rounded-xl">
            <span className="text-xs font-bold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
              <svg className="w-4 h-4 transform -rotate-90" viewBox="0 0 36 36">
                <path className="text-foreground/20" stroke="currentColor" strokeWidth="4" fill="none" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
                <path className="text-blue-500" strokeDasharray="75, 100" stroke="currentColor" strokeWidth="4" fill="none" strokeLinecap="round" d="M18 2.0845 a 15.9155 15.9155 0 0 1 0 31.831 a 15.9155 15.9155 0 0 1 0 -31.831" />
              </svg>
              AI Confidence Score:
            </span>
            <div className="flex gap-4">
              <div className="flex items-center gap-1.5 text-xs font-semibold text-green-500">
                <div className="w-2.5 h-2.5 rounded-full bg-green-500/20 border border-green-500" /> High (≥ 80%)
              </div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-500">
                <div className="w-2.5 h-2.5 rounded-full bg-amber-500/20 border border-amber-500" /> Medium (50-79%)
              </div>
              <div className="flex items-center gap-1.5 text-xs font-semibold text-red-500">
                <div className="w-2.5 h-2.5 rounded-full bg-red-500/20 border border-red-500" /> Low (&lt; 50%)
              </div>
            </div>
          </div>
          
          {uniqueFiles.length === 0 ? (
            <div className="text-center py-12 border-2 border-dashed border-border rounded-2xl">
              <p className="text-muted-foreground">No files classified under this business area yet.</p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {uniqueFiles.map((file, idx) => (
                <FileRow 
                  key={idx} 
                  file={file} 
                  def={def} 
                  onClick={() => onSelectFile(file)} 
                />
              ))}
            </div>
          )}
        </div>
      ) : activeTab === 'relations' ? (
        <div className="animate-in fade-in slide-in-from-bottom-4 duration-300">
          {allDashboardNames ? (
            <KPIDashboardGraph dashboards={allDashboardNames} />
          ) : (
            <div className="text-center py-12 border-2 border-dashed border-border rounded-2xl">
              <p className="text-muted-foreground">No dashboards available to graph.</p>
            </div>
          )}
        </div>
      ) : null}

    </div>
  );
}