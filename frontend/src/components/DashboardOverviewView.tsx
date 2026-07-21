import { API_BASE_URL } from '@/config';
import React, { useMemo, useState, useEffect } from 'react';
import { LayoutDashboard, Filter, ChevronDown, Check, FolderOpen, Sparkles, FileSpreadsheet, Calculator, Table, ArrowRight, BarChart2, Database } from 'lucide-react';
import { getWorkbookAreaId, AREAS } from './BusinessAreasView';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

function KPICard({ icon, title, value, subtitle, color, isActive, onClick }: {
  icon: React.ReactNode;
  title: string;
  value: number;
  subtitle: string;
  color: string;
  isActive?: boolean;
  onClick?: () => void;
}) {
  return (
    <Card 
      onClick={onClick}
      className={`transition-all ${isActive ? 'ring-2 ring-primary border-transparent shadow-md' : 'hover:border-primary/50'} ${onClick ? 'cursor-pointer' : 'cursor-default'}`}
    >
      <CardHeader className={`flex flex-row items-center justify-between space-y-0 pb-2`}>
        <CardTitle className={`text-xs font-semibold uppercase tracking-wider ${isActive ? 'text-primary' : 'text-muted-foreground'}`}>{title}</CardTitle>
        <div className={`p-1.5 rounded-lg ${color}`}>
          {React.cloneElement(icon as React.ReactElement<any>, { className: 'w-4 h-4' })}
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-bold tracking-tight">{value}</p>
        <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

// Helper component for a custom dropdown filter
function DropdownFilter({ label, options, selectedValue, onChange }: { 
  label: string; 
  options: string[]; 
  selectedValue: string | null; 
  onChange: (val: string | null) => void 
}) {
  const [isOpen, setIsOpen] = useState(false);

  return (
    <div className="relative">
      <div 
        onClick={() => setIsOpen(!isOpen)}
        className={`flex items-center justify-between gap-3 px-4 py-2.5 rounded-lg border text-sm font-medium cursor-pointer transition-colors shadow-sm
          ${selectedValue 
            ? 'border-primary/50 bg-primary/10 text-primary' 
            : 'border-border bg-sidebar hover:bg-accent text-foreground'
          }`}
      >
        <span className="truncate max-w-[150px]">
          {selectedValue || label}
        </span>
        <ChevronDown className="w-4 h-4 opacity-70" />
      </div>

      {isOpen && (
        <div className="absolute top-full left-0 mt-2 w-64 max-h-60 overflow-y-auto bg-popover border border-border rounded-xl shadow-xl z-50 p-1">
          <div 
            onClick={() => { onChange(null); setIsOpen(false); }}
            className={`px-3 py-2 rounded-md text-sm cursor-pointer transition-colors flex items-center justify-between
              ${!selectedValue ? 'bg-primary/15 text-primary font-medium' : 'hover:bg-accent text-foreground'}`}
          >
            All {label}
            {!selectedValue && <Check className="w-4 h-4" />}
          </div>
          {options.map((opt, idx) => (
            <div 
              key={idx}
              onClick={() => { onChange(opt); setIsOpen(false); }}
              className={`px-3 py-2 rounded-md text-sm cursor-pointer transition-colors flex items-center justify-between mt-0.5
                ${selectedValue === opt ? 'bg-primary/15 text-primary font-medium' : 'hover:bg-accent text-foreground'}`}
            >
              <span className="truncate">{opt}</span>
              {selectedValue === opt && <Check className="w-4 h-4 shrink-0" />}
            </div>
          ))}
        </div>
      )}
      
      {/* Backdrop for closing dropdown */}
      {isOpen && (
        <div className="fixed inset-0 z-40" onClick={() => setIsOpen(false)} />
      )}
    </div>
  );
}

export function DashboardOverviewView({ 
  workbooksData,
  onSelectDashboard
}: { 
  workbooksData: any[];
  onSelectDashboard: (workbook: any, dashboard: any) => void;
}) {
  const [aiSummariesMap, setAiSummariesMap] = useState<Record<string, any>>({});

  useEffect(() => {
    workbooksData.forEach(wb => {
      const workbookBaseName = wb.source_file?.split(/[/\\]/).pop() || wb.source_file;
      if (!workbookBaseName) return;

      // Only fetch if we haven't already
      setAiSummariesMap(prev => {
        if (prev[workbookBaseName]) return prev;
        
        fetch(`${API_BASE_URL}/api/v1/agent/workbook-summary?workbook_name=${encodeURIComponent(workbookBaseName)}`)
          .then(r => r.json())
          .then(data => {
            setAiSummariesMap(curr => ({ ...curr, [workbookBaseName]: data }));
          })
          .catch(() => {});
          
        // Preemptively add a placeholder so we don't fetch multiple times for the same workbook
        return { ...prev, [workbookBaseName]: { loading: true } };
      });
    });
  }, [workbooksData]);

  // 1. Flatten all dashboards
  const allDashboards = useMemo(() => {
    const list: any[] = [];
    workbooksData.forEach(wb => {
      if (wb.dashboards && Array.isArray(wb.dashboards)) {
        wb.dashboards.forEach((db: any) => {
          list.push({ ...db, workbook: wb });
        });
      }
    });
    return list;
  }, [workbooksData]);

  // 2. Extract unique options for independent filters
  const allLOBs = useMemo(() => {
    const lobs = new Set<string>();
    allDashboards.forEach(d => {
      if (d.line_of_business) lobs.add(d.line_of_business);
    });
    return Array.from(lobs).sort();
  }, [allDashboards]);

  const allUserGroups = useMemo(() => {
    const groups = new Set<string>();
    allDashboards.forEach(d => {
      const workbookBaseName = d.workbook.source_file?.split(/[/\\]/).pop() || d.workbook.source_file;
      const aiDb = aiSummariesMap[workbookBaseName]?.dashboards?.find((a: any) => a.name === d.name);
      const userGroups = aiDb?.user_groups || d.user_groups;
      
      if (Array.isArray(userGroups)) {
        userGroups.forEach((g: string) => groups.add(g));
      } else if (typeof userGroups === 'string') {
        userGroups.split(',').forEach((g: string) => groups.add(g.trim()));
      }
    });
    return Array.from(groups).filter(Boolean).sort();
  }, [allDashboards, aiSummariesMap]);

  const allBusinessAreas = useMemo(() => {
    const areas = new Set<string>();
    allDashboards.forEach(d => {
      const areaId = getWorkbookAreaId(d.workbook);
      const areaDef = AREAS.find(a => a.id === areaId);
      if (areaDef) areas.add(areaDef.title);
    });
    return Array.from(areas).sort();
  }, [allDashboards]);

  // 3. Filter States
  const [selectedLOB, setSelectedLOB] = useState<string | null>(null);
  const [selectedUserGroup, setSelectedUserGroup] = useState<string | null>(null);
  const [selectedBusinessArea, setSelectedBusinessArea] = useState<string | null>(null);
  const [selectedDashboardName, setSelectedDashboardName] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<'dashboards' | 'worksheets' | 'calcFields' | 'tables'>('dashboards');
  const [selectedWorksheet, setSelectedWorksheet] = useState<string | null>(null);

  // 4. Compute Dashboard Names based on first 3 filters
  const availableDashboardNames = useMemo(() => {
    const names = new Set<string>();
    allDashboards.forEach(d => {
      let matchLOB = !selectedLOB || d.line_of_business === selectedLOB;
      
      let matchGroup = !selectedUserGroup;
      if (selectedUserGroup) {
        const workbookBaseName = d.workbook.source_file?.split(/[/\\]/).pop() || d.workbook.source_file;
        const aiDb = aiSummariesMap[workbookBaseName]?.dashboards?.find((a: any) => a.name === d.name);
        const userGroups = aiDb?.user_groups || d.user_groups;
        
        if (Array.isArray(userGroups)) {
          matchGroup = userGroups.includes(selectedUserGroup);
        } else if (typeof userGroups === 'string') {
          matchGroup = userGroups.includes(selectedUserGroup);
        }
      }

      let matchArea = !selectedBusinessArea;
      if (selectedBusinessArea) {
        const areaId = getWorkbookAreaId(d.workbook);
        const areaDef = AREAS.find(a => a.id === areaId);
        matchArea = areaDef?.title === selectedBusinessArea;
      }

      if (matchLOB && matchGroup && matchArea) {
        names.add(d.name);
      }
    });
    return Array.from(names).sort();
  }, [allDashboards, selectedLOB, selectedUserGroup, selectedBusinessArea, aiSummariesMap]);

  // If the currently selected dashboard name is no longer valid, reset it
  if (selectedDashboardName && !availableDashboardNames.includes(selectedDashboardName)) {
    setSelectedDashboardName(null);
  }

  // 5. Final Displayed Dashboards
  const displayedDashboards = useMemo(() => {
    return allDashboards.filter(d => {
      let matchLOB = !selectedLOB || d.line_of_business === selectedLOB;
      
      let matchGroup = !selectedUserGroup;
      if (selectedUserGroup) {
        const workbookBaseName = d.workbook.source_file?.split(/[/\\]/).pop() || d.workbook.source_file;
        const aiDb = aiSummariesMap[workbookBaseName]?.dashboards?.find((a: any) => a.name === d.name);
        const userGroups = aiDb?.user_groups || d.user_groups;
        
        if (Array.isArray(userGroups)) {
          matchGroup = userGroups.includes(selectedUserGroup);
        } else if (typeof userGroups === 'string') {
          matchGroup = userGroups.includes(selectedUserGroup);
        }
      }

      let matchArea = !selectedBusinessArea;
      if (selectedBusinessArea) {
        const areaId = getWorkbookAreaId(d.workbook);
        const areaDef = AREAS.find(a => a.id === areaId);
        matchArea = areaDef?.title === selectedBusinessArea;
      }

      let matchName = !selectedDashboardName || d.name === selectedDashboardName;

      return matchLOB && matchGroup && matchArea && matchName;
    });
  }, [allDashboards, selectedLOB, selectedUserGroup, selectedBusinessArea, selectedDashboardName, aiSummariesMap]);

  // Compute filtered assets based on displayedDashboards
  const filteredAssets = useMemo(() => {
    const uniqueWorkbooks = new Set<any>();
    displayedDashboards.forEach(d => uniqueWorkbooks.add(d.workbook));

    const worksheets: any[] = [];
    const allCalcFields: any[] = [];
    const allTables: any[] = [];

    Array.from(uniqueWorkbooks).forEach((wb: any) => {
      if (wb.worksheets) {
        worksheets.push(...wb.worksheets.map((w: any) => ({ ...w, workbookName: wb.source_file })));
      }
      if (wb.datasources) {
        wb.datasources.forEach((ds: any) => {
          if (ds.calculated_fields) {
            ds.calculated_fields.forEach((cf: any) => allCalcFields.push({ ...cf, dsName: ds.caption || ds.name, workbookName: wb.source_file }));
          }
          if (ds.tables) {
            ds.tables.forEach((t: any) => allTables.push({ name: t.name, dsName: ds.name, columns: t.columns_preview || [], rows: t.rows_preview || [], workbookName: wb.source_file }));
          }
        });
      }
    });

    return {
      workbooks: Array.from(uniqueWorkbooks),
      worksheets,
      calcFields: allCalcFields,
      tables: allTables,
    };
  }, [displayedDashboards]);



  return (
    <div className="flex-1 overflow-auto bg-background p-8">
      <div className="max-w-7xl mx-auto space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
        
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground flex items-center gap-3">
            <LayoutDashboard className="w-8 h-8 text-primary" />
            Dashboard Overview
          </h1>
          <p className="text-muted-foreground mt-2 text-lg">
            Explore and filter all {allDashboards.length} discovered dashboards across the enterprise.
          </p>
        </div>

        {/* Filters */}
        <div className="bg-card border border-border rounded-xl p-5 shadow-sm space-y-4">
          <div className="flex items-center gap-2 text-sm font-semibold text-muted-foreground uppercase tracking-wider mb-2">
            <Filter className="w-4 h-4" />
            Global Filters
          </div>
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <DropdownFilter 
              label="Line of Business" 
              options={allLOBs} 
              selectedValue={selectedLOB} 
              onChange={setSelectedLOB} 
            />
            <DropdownFilter 
              label="User Group" 
              options={allUserGroups} 
              selectedValue={selectedUserGroup} 
              onChange={setSelectedUserGroup} 
            />
            <DropdownFilter 
              label="Business Area" 
              options={allBusinessAreas} 
              selectedValue={selectedBusinessArea} 
              onChange={setSelectedBusinessArea} 
            />
            <DropdownFilter 
              label="Dashboard Name" 
              options={availableDashboardNames} 
              selectedValue={selectedDashboardName} 
              onChange={setSelectedDashboardName} 
            />
          </div>
        </div>

        {/* KPI Row (Tab Switchers) */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          <KPICard
            icon={<LayoutDashboard />}
            title="Dashboards"
            value={displayedDashboards.length}
            subtitle="Filtered dashboards"
            color="bg-blue-500/15 text-blue-400"
            isActive={activeTab === 'dashboards'}
            onClick={() => setActiveTab('dashboards')}
          />
          <KPICard
            icon={<FileSpreadsheet />}
            title="Worksheets"
            value={filteredAssets.worksheets.length}
            subtitle="Individual views"
            color="bg-emerald-500/15 text-emerald-400"
            isActive={activeTab === 'worksheets'}
            onClick={() => setActiveTab('worksheets')}
          />
          <KPICard
            icon={<Calculator />}
            title="Calculated Fields"
            value={filteredAssets.calcFields.length}
            subtitle="Custom business logic"
            color="bg-purple-500/15 text-purple-400"
            isActive={activeTab === 'calcFields'}
            onClick={() => setActiveTab('calcFields')}
          />
          <KPICard
            icon={<Table />}
            title="Data Sources"
            value={filteredAssets.tables.length}
            subtitle="Physical database tables"
            color="bg-rose-500/15 text-rose-400"
            isActive={activeTab === 'tables'}
            onClick={() => setActiveTab('tables')}
          />
        </div>

        {/* TAB: Dashboards */}
        {activeTab === 'dashboards' && (
          <Card className="animate-in fade-in duration-300">
            <CardHeader className="border-b border-border pb-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Dashboard Inventory</CardTitle>
                <span className="text-xs text-muted-foreground">{displayedDashboards.length} total</span>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              <div className="grid grid-cols-12 px-6 py-3 bg-muted/30 border-b border-border text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <span className="col-span-10">Dashboard & AI Summary</span>
                <span className="col-span-2 text-right">Action</span>
              </div>
              <div className="divide-y divide-border">
                {displayedDashboards.length > 0 ? (
                  displayedDashboards.map((db, idx) => {
                    const workbookBaseName = db.workbook.source_file?.split(/[/\\]/).pop() || db.workbook.source_file;
                    const aiDb = aiSummariesMap[workbookBaseName]?.dashboards?.find((d: any) => d.name === db.name);
                    return (
                      <div
                        key={idx}
                        className="grid grid-cols-12 px-6 py-4 items-start hover:bg-accent/30 transition-colors group border-b border-border/50 last:border-0"
                      >
                        <div className="col-span-10 flex items-start gap-3 pt-0.5">
                          <div className="w-7 h-7 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                            <LayoutDashboard className="w-3.5 h-3.5 text-primary" />
                          </div>
                          <div className="min-w-0 flex-1 space-y-1.5">
                            <div className="flex items-center gap-2">
                              <p className="font-semibold text-sm text-foreground truncate">{db.name}</p>
                              {aiDb?.domain ? (
                                <span className="inline-block px-1.5 py-0.5 rounded bg-primary/10 text-primary text-[10px] font-bold border border-primary/15">
                                  {aiDb.domain}
                                </span>
                              ) : (
                                <span className="text-[10px] text-muted-foreground px-1.5 py-0.5 border border-border rounded">Tableau Dashboard</span>
                              )}
                              {aiDb && (
                                aiDb.is_real_ai ? (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 text-[8px] font-bold border border-emerald-500/20 uppercase tracking-wider">
                                    <Sparkles className="w-2.5 h-2.5 inline-block mr-0.5 flex-shrink-0" /> Live AI Summary
                                  </span>
                                ) : (
                                  <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 text-[8px] font-bold border border-amber-500/20 uppercase tracking-wider">
                                    AI Governance Fallback
                                  </span>
                                )
                              )}
                              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-muted text-[10px] font-medium text-muted-foreground ml-2">
                                <FolderOpen className="w-3 h-3" /> {db.workbook.source_file}
                              </span>
                            </div>
                            {aiDb?.summary ? (
                              <p className="text-[11px] text-muted-foreground leading-relaxed pr-8">{aiDb.summary}</p>
                            ) : (
                              <p className="text-[11px] text-muted-foreground/40 italic">No AI summary available for this dashboard.</p>
                            )}
                          </div>
                        </div>
                        
                        <div className="col-span-2 flex justify-end pt-1">
                          <button
                            onClick={() => onSelectDashboard(db.workbook, db)}
                            className="flex items-center gap-1 px-3 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground rounded-lg text-xs font-medium transition-all opacity-0 group-hover:opacity-100 shadow-sm"
                          >
                            Details
                            <ArrowRight className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </div>
                    );
                  })
                ) : (
                  <div className="px-6 py-12 text-center text-muted-foreground text-sm">
                    No dashboards found matching your filters.
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* TAB: Worksheets */}
        {activeTab === 'worksheets' && (
          <div className="space-y-6 animate-in fade-in duration-300">
            <Card>
              <CardHeader className="border-b border-border pb-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base">Worksheets</CardTitle>
                  <span className="text-xs text-muted-foreground">{filteredAssets.worksheets.length} total</span>
                </div>
              </CardHeader>
              <CardContent className="p-4">
                {filteredAssets.worksheets.length > 0 ? (
                  <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {filteredAssets.worksheets.map((ws: any, idx: number) => {
                      const isSelected = selectedWorksheet === ws.name;
                      return (
                        <li 
                          key={idx}
                          className={`rounded-lg border transition-all ${isSelected ? 'border-primary shadow-sm bg-primary/5' : 'border-border bg-card hover:bg-accent/50'}`}
                        >
                          <div 
                            className="flex items-start justify-between px-4 py-3 cursor-pointer"
                            onClick={() => setSelectedWorksheet(isSelected ? null : ws.name)}
                          >
                            <div className="flex items-center gap-3">
                              <div className={`p-1.5 rounded-md ${isSelected ? 'bg-primary text-primary-foreground' : 'bg-primary/10 text-primary'}`}>
                                <FileSpreadsheet className="w-4 h-4" />
                              </div>
                              <div className="flex flex-col">
                                <span className="text-sm font-semibold text-foreground">{ws.name}</span>
                                <span className="text-[10px] text-muted-foreground mt-0.5">Workbook: {ws.workbookName}</span>
                              </div>
                            </div>
                            <ChevronDown className={`w-4 h-4 text-muted-foreground transition-transform ${isSelected ? 'rotate-180' : ''}`} />
                          </div>
                          
                          {isSelected && (
                            <div className="px-4 pb-4 pt-2 border-t border-primary/10 bg-background/50 rounded-b-lg text-xs animate-in slide-in-from-top-2 duration-200">
                              <div className="mb-3">
                                <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">Graph Type</span>
                                <span className="font-medium text-amber-400 flex items-center gap-1.5">
                                  <BarChart2 className="w-3.5 h-3.5"/>
                                  {ws.mark_type || 'Automatic'}
                                </span>
                              </div>
                              
                              <div className="space-y-2.5">
                                <div>
                                  <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">X-Axis (Columns)</span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {ws.columns?.length > 0 ? ws.columns.map((c: string, i: number) => (
                                      <span key={i} className="px-1.5 py-0.5 bg-blue-500/15 text-blue-400 border border-blue-500/20 rounded font-mono">{c}</span>
                                    )) : <span className="text-muted-foreground italic text-xs">None</span>}
                                  </div>
                                </div>
                                
                                <div>
                                  <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">Y-Axis (Rows)</span>
                                  <div className="flex flex-wrap gap-1.5">
                                    {ws.rows?.length > 0 ? ws.rows.map((r: string, i: number) => (
                                      <span key={i} className="px-1.5 py-0.5 bg-purple-500/15 text-purple-400 border border-purple-500/20 rounded font-mono">{r}</span>
                                    )) : <span className="text-muted-foreground italic text-xs">None</span>}
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}
                        </li>
                      );
                    })}
                  </ul>
                ) : (
                  <p className="text-sm text-muted-foreground italic py-4 text-center">No worksheets detected.</p>
                )}
              </CardContent>
            </Card>
          </div>
        )}



        {/* TAB: Calculated Fields */}
        {activeTab === 'calcFields' && (
          <Card className="animate-in fade-in duration-300">
            <CardHeader className="border-b border-border pb-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Calculated Fields</CardTitle>
                <span className="text-xs text-muted-foreground">{filteredAssets.calcFields.length} total</span>
              </div>
            </CardHeader>
            <CardContent className="p-4">
              {filteredAssets.calcFields.length > 0 ? (
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {filteredAssets.calcFields.map((cf: any, idx: number) => (
                    <div key={idx} className="p-4 rounded-xl border border-border bg-muted/20 flex flex-col gap-2">
                      <div className="flex justify-between items-start gap-2">
                        <div className="flex items-center gap-2 text-purple-400 font-semibold">
                          <Calculator className="w-4 h-4" />
                          <span className="truncate max-w-[200px]">{cf.name}</span>
                        </div>
                        <span className="px-2 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-500 border border-amber-500/20 truncate max-w-[120px]">
                          {cf.dsName}
                        </span>
                      </div>
                      <code className="mt-2 text-xs text-muted-foreground break-all leading-relaxed whitespace-pre-wrap bg-background p-2 rounded border border-border/50 max-h-40 overflow-y-auto">
                        {cf.formula || 'No formula available'}
                      </code>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-muted-foreground italic py-4 text-center">No calculated fields detected.</p>
              )}
            </CardContent>
          </Card>
        )}

        {/* TAB: Tables */}
        {activeTab === 'tables' && (
          <div className="space-y-6 animate-in fade-in duration-300">
            <Card>
              <CardHeader className="border-b border-border pb-4">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-base flex items-center gap-2">
                    <Table className="w-5 h-5 text-primary" />
                    Table Data Preview
                  </CardTitle>
                  <span className="text-xs text-muted-foreground">{filteredAssets.tables.length} tables found</span>
                </div>
              </CardHeader>
              <CardContent className="p-6">
                {filteredAssets.tables.length === 0 ? (
                  <p className="text-sm text-muted-foreground italic text-center py-8">No physical tables detected.</p>
                ) : (
                  <div className="space-y-8">
                    {filteredAssets.tables.map((t, idx) => (
                      <div key={idx} className="rounded-xl border border-border overflow-hidden">
                        <div className="flex items-center gap-3 px-4 py-3 bg-violet-500/10 border-b border-border">
                          <div className="w-7 h-7 rounded-lg bg-violet-500/20 flex items-center justify-center flex-shrink-0">
                            <Table className="w-4 h-4 text-violet-400" />
                          </div>
                          <div>
                            <p className="text-sm font-bold text-foreground">{t.name}</p>
                            <p className="text-[10px] text-muted-foreground">via datasource: <span className="text-amber-400">{t.dsName}</span></p>
                          </div>
                          <span className="ml-auto text-[10px] px-2 py-0.5 rounded-full bg-violet-500/20 text-violet-400 border border-violet-500/30 font-medium">
                            {t.rows.length} row{t.rows.length !== 1 ? 's' : ''} preview
                          </span>
                        </div>

                        {t.columns.length > 0 && t.rows.length > 0 ? (
                          <div className="overflow-x-auto">
                            <table className="w-full text-xs border-collapse min-w-max">
                              <thead>
                                <tr className="bg-muted/40 border-b border-border">
                                  <th className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground w-8 border-r border-border/50">#</th>
                                  {t.columns.map((col: string, ci: number) => (
                                    <th key={ci} className="px-3 py-2 text-left text-[10px] font-bold uppercase tracking-wider text-muted-foreground border-r border-border/50 last:border-0 whitespace-nowrap">
                                      <span className="font-mono text-sky-400">{col}</span>
                                    </th>
                                  ))}
                                </tr>
                              </thead>
                              <tbody>
                                {t.rows.map((row: string[], ri: number) => (
                                  <tr key={ri} className={`border-b border-border/50 last:border-0 hover:bg-accent/20 transition-colors ${ri % 2 === 0 ? '' : 'bg-muted/10'}`}>
                                    <td className="px-3 py-2.5 text-center text-[10px] text-muted-foreground font-mono border-r border-border/50">{ri + 1}</td>
                                    {row.map((cell: string, ci: number) => (
                                      <td key={ci} className="px-3 py-2.5 text-foreground/90 font-mono border-r border-border/50 last:border-0 whitespace-nowrap max-w-[200px] truncate">
                                        {cell === '' || cell === 'None' || cell === 'null' ? (
                                          <span className="text-muted-foreground/40 italic text-[10px]">null</span>
                                        ) : cell}
                                      </td>
                                    ))}
                                  </tr>
                                ))}
                              </tbody>
                            </table>
                          </div>
                        ) : t.columns.length > 0 ? (
                          <div className="p-4">
                            <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-3">Column Schema <span className="text-muted-foreground/50 font-normal ml-1">— no data preview available (.twb without extract)</span></p>
                            <div className="flex flex-wrap gap-2">
                              {t.columns.map((col: string, ci: number) => (
                                <span key={ci} className="px-2 py-1 rounded-md bg-violet-500/10 border border-violet-500/20 text-violet-300 text-[11px] font-mono">{col}</span>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-center justify-center gap-2 py-8 text-muted-foreground text-sm">
                            <Database className="w-4 h-4" />
                            <span>No column information available.</span>
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        )}

      </div>
    </div>
  );
}