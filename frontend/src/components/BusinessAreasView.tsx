import { API_BASE_URL } from '@/config';
import React, { useMemo, useState } from 'react';
import { Briefcase, FileText, ShieldAlert, CreditCard, Activity, LineChart, ChevronRight, Target, Users, Filter, ChevronDown } from 'lucide-react';
import { ChatPanel } from './ChatPanel';

export const AREAS = [
  { id: 'claims-risk', title: 'Claims & Risk', icon: ShieldAlert, color: 'text-rose-500', bg: 'bg-rose-500/10', border: 'border-rose-500/20' },
  { id: 'customer-service', title: 'Customer Service', icon: Users, color: 'text-indigo-500', bg: 'bg-indigo-500/10', border: 'border-indigo-500/20' },
  { id: 'new-business-ops', title: 'New Business Ops', icon: Briefcase, color: 'text-blue-500', bg: 'bg-blue-500/10', border: 'border-blue-500/20' },
  { id: 'sales-pipeline', title: 'Sales & pipeline', icon: Target, color: 'text-amber-500', bg: 'bg-amber-500/10', border: 'border-amber-500/20' },
  { id: 'product-level-performance', title: 'Product Level Performance', icon: LineChart, color: 'text-purple-500', bg: 'bg-purple-500/10', border: 'border-purple-500/20' },
];

export function getWorkbookAreaId(wb: any, aiSummariesMap: Record<string, any> = {}): string {
  const workbookBaseName = wb?.source_file?.split(/[/\\]/).pop() || wb?.source_file;
  const aiData = workbookBaseName ? aiSummariesMap[workbookBaseName] : null;
  
  let domain = 'claims-risk';
  if (aiData && aiData.workbook_domain) {
      domain = aiData.workbook_domain;
  } else if (wb && wb.dashboards && wb.dashboards.length > 0) {
      domain = wb.dashboards[0].domain || 'claims-risk';
  }
  
  const normalized = domain.toLowerCase().trim();
  
  if (normalized.includes('claims') || normalized.includes('risk')) return 'claims-risk';
  if (normalized.includes('customer service')) return 'customer-service';
  if (normalized.includes('new business')) return 'new-business-ops';
  if (normalized.includes('sales') || normalized.includes('pipeline')) return 'sales-pipeline';
  if (normalized.includes('product')) return 'product-level-performance';
  
  return 'claims-risk';
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

export function BusinessAreasView({ 
  workbooksData, 
  selectedLOBs,
  setSelectedLOBs,
  selectedUserGroups,
  setSelectedUserGroups,
  onSelectArea 
}: { 
  workbooksData: any[]; 
  selectedLOBs: string[];
  setSelectedLOBs: React.Dispatch<React.SetStateAction<string[]>>;
  selectedUserGroups: string[];
  setSelectedUserGroups: React.Dispatch<React.SetStateAction<string[]>>;
  onSelectArea: (areaId: string) => void;
}) {
  const [isLOBOpen, setIsLOBOpen] = useState(false);
  const [isGroupOpen, setIsGroupOpen] = useState(false);
  const [aiSummariesMap, setAiSummariesMap] = useState<Record<string, any>>({});
  
  React.useEffect(() => {
    const fetchAiSummaries = async () => {
      const summaries: Record<string, any> = {};
      if (!workbooksData) return;
      for (const wb of workbooksData) {
        try {
          const workbookBaseName = wb.source_file?.split(/[/\\]/).pop() || wb.source_file;
          const res = await fetch(`${API_BASE_URL}/api/v1/agent/workbook-summary?workbook_name=${encodeURIComponent(workbookBaseName)}`);
          if (res.ok) {
            const data = await res.json();
            summaries[workbookBaseName] = data;
          }
        } catch (e) {
          console.error("Error fetching AI summary", e);
        }
      }
      setAiSummariesMap(summaries);
    };
    fetchAiSummaries();
  }, [workbooksData]);
  
  const availableUserGroups = ALL_USER_GROUPS;

  const availableLOBs = ALL_LOBS;

  const filteredWorkbooks = useMemo(() => {
    if (!workbooksData) return [];
    return workbooksData.filter(file => {
      if (!file.dashboards || file.dashboards.length === 0) {
        return selectedLOBs.length === 0 && selectedUserGroups.length === 0;
      }
      
      return file.dashboards.some((dash: any) => {
        const workbookBaseName = file.source_file?.split(/[/\\]/).pop() || file.source_file;
        const aiDb = aiSummariesMap[workbookBaseName]?.dashboards?.find((a: any) => a.name === dash.name);
        
        const lob = aiDb?.line_of_business || dash?.line_of_business;
        const groups = aiDb?.user_groups || dash?.user_groups;
        
        const lobMatch = selectedLOBs.length === 0 || 
          (lob && selectedLOBs.some(sl => sl.toLowerCase().trim() === String(lob).toLowerCase().trim()));
          
        const groupArray = Array.isArray(groups) ? groups : (typeof groups === 'string' ? groups.split(',').map(s => s.trim()) : []);
        const groupMatch = selectedUserGroups.length === 0 || 
          groupArray.some((g: string) => selectedUserGroups.some(sg => sg.toLowerCase().trim() === String(g).toLowerCase().trim()));
        
        return lobMatch && groupMatch;
      });
    });
  }, [workbooksData, selectedLOBs, selectedUserGroups, aiSummariesMap]);

  // Calculate actual distribution of files across areas based on AI domain
  const distribution = useMemo(() => {
    const dist: Record<string, number> = {};
    AREAS.forEach(a => dist[a.id] = 0);
    
    if (filteredWorkbooks && filteredWorkbooks.length > 0) {
      filteredWorkbooks.forEach((wb) => {
        const areaId = getWorkbookAreaId(wb, aiSummariesMap);
        if (dist[areaId] !== undefined) {
          dist[areaId]++;
        }
      });
    }
    return dist;
  }, [filteredWorkbooks, aiSummariesMap]);

  const totalFiles = filteredWorkbooks?.length || 0;

  return (
    <div className="space-y-8 animate-in fade-in zoom-in-95 duration-300 max-w-6xl mx-auto py-4">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-foreground">Business Areas</h2>
          <p className="text-muted-foreground mt-1.5 text-sm max-w-2xl">
            Select a business domain to view its specific Tableau dashboards and analytical assets.
          </p>
          <div className="mt-6 inline-flex items-center gap-3 px-4 py-2.5 bg-primary/10 border border-primary/20 rounded-xl shadow-sm">
            <div className="flex items-center justify-center w-8 h-8 rounded-lg bg-primary/20 text-primary font-bold">
              {totalFiles}
            </div>
            <span className="text-sm font-semibold text-primary/90 uppercase tracking-wide">
              {totalFiles === 1 ? 'Dashboard' : 'Dashboards'} Analyzed
            </span>
          </div>
        </div>
        <div className="flex flex-col items-end gap-3">
          <div className="flex items-center justify-end gap-3 mt-2">
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
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {AREAS.map((area) => {
          const count = distribution[area.id] || 0;
          const Icon = area.icon;
          
          const isFilterActive = selectedLOBs.length > 0 || selectedUserGroups.length > 0;
          const isHighlighted = isFilterActive && count > 0;
          const isDimmed = count === 0;

          return (
            <div
              key={area.id}
              onClick={() => {
                if (!isDimmed) onSelectArea(area.id);
              }}
              className={`group relative overflow-hidden rounded-2xl border bg-card transition-all duration-500 p-6 flex flex-col h-48
                ${isDimmed ? 'opacity-40 grayscale border-border cursor-not-allowed hover:opacity-60' : `cursor-pointer ${area.border}`}
                ${isHighlighted ? 'ring-2 ring-primary ring-offset-2 ring-offset-background shadow-xl scale-[1.02]' : (!isDimmed ? 'hover:shadow-lg' : '')}
              `}
            >
              {/* Background accent */}
              <div className={`absolute top-0 right-0 w-32 h-32 -mr-8 -mt-8 rounded-full ${area.bg} opacity-50 transition-transform duration-500 group-hover:scale-150 ${isHighlighted ? 'scale-150 animate-pulse' : ''}`} />
              
              <div className="relative z-10 flex-1">
                <div className={`w-12 h-12 rounded-xl ${area.bg} flex items-center justify-center mb-4`}>
                  <Icon className={`w-6 h-6 ${area.color}`} />
                </div>
                
                <h3 className="text-xl font-bold text-foreground mb-1 group-hover:text-primary transition-colors">
                  {area.title}
                </h3>
                
                <p className="text-sm text-muted-foreground">
                  {count} {count === 1 ? 'Dashboard' : 'Dashboards'}
                </p>
              </div>

              <div className="relative z-10 mt-auto flex items-center justify-between opacity-0 group-hover:opacity-100 transition-all duration-300 translate-y-2 group-hover:translate-y-0">
                <span className="text-sm font-semibold text-primary">View Portfolio</span>
                <div className={`w-8 h-8 rounded-full ${area.bg} flex items-center justify-center`}>
                  <ChevronRight className={`w-4 h-4 ${area.color}`} />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Global Conversational BI */}
      <ChatPanel workbookName="Global Portfolio" />
    </div>
  );
}