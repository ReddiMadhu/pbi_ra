import React, { useMemo, useState } from 'react';
import { Filter, Users, ChevronDown } from 'lucide-react';
import { KPIDashboardGraph } from './KPIDashboardGraph';

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

export function LandscapeView({ 
  workbooksData, 
  selectedLOBs,
  setSelectedLOBs,
  selectedUserGroups,
  setSelectedUserGroups
}: { 
  workbooksData: any[]; 
  selectedLOBs: string[];
  setSelectedLOBs: React.Dispatch<React.SetStateAction<string[]>>;
  selectedUserGroups: string[];
  setSelectedUserGroups: React.Dispatch<React.SetStateAction<string[]>>;
}) {
  const [isLOBOpen, setIsLOBOpen] = useState(false);
  const [isGroupOpen, setIsGroupOpen] = useState(false);
  
  const availableUserGroups = ALL_USER_GROUPS;
  const availableLOBs = ALL_LOBS;

  const filteredDashboardsString = useMemo(() => {
    if (!workbooksData) return '';
    const dashes: string[] = [];
    workbooksData.forEach(wb => {
      if (!wb.dashboards) return;
      wb.dashboards.forEach((dash: any) => {
        const lob = dash?.line_of_business;
        const groups = dash?.user_groups;
        
        const lobMatch = selectedLOBs.length === 0 || 
          (lob && selectedLOBs.some(sl => sl.toLowerCase().trim() === String(lob).toLowerCase().trim()));
          
        const groupArray = Array.isArray(groups) ? groups : (typeof groups === 'string' ? groups.split(',').map(s => s.trim()) : []);
        const groupMatch = selectedUserGroups.length === 0 || 
          groupArray.some((g: string) => selectedUserGroups.some(sg => sg.toLowerCase().trim() === String(g).toLowerCase().trim()));
        
        if (lobMatch && groupMatch) {
           if (dash.name) {
             dashes.push(dash.name);
           }
        }
      });
    });
    return dashes.join(',');
  }, [workbooksData, selectedLOBs, selectedUserGroups]);

  return (
    <div className="space-y-6 animate-in fade-in zoom-in-95 duration-300 max-w-6xl mx-auto py-4">
      {/* Header & Global Filters */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-3xl font-bold tracking-tight text-foreground">BI Landscape Graph</h2>
          <p className="text-muted-foreground mt-1.5 text-sm max-w-2xl">
            Interactive visualization of your entire dashboard lineage and KPI relationships.
          </p>
        </div>
        
        <div className="flex items-center gap-3">
          {/* LOB Filter Dropdown */}
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
          
          {/* User Group Filter Dropdown */}
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
        </div>
      </div>

      {/* Graph Area */}
      <div className="w-full">
        {filteredDashboardsString ? (
          <KPIDashboardGraph dashboards={filteredDashboardsString} />
        ) : (
          <div className="flex flex-col items-center justify-center h-[600px] bg-slate-950 rounded-xl border border-slate-800">
            <p className="text-slate-400 font-semibold">No dashboards match the selected filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
