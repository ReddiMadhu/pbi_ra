import { API_BASE_URL } from '@/config';
import React, { useState, useEffect } from 'react';
import { Database, LayoutDashboard, FileSpreadsheet, Calculator, ArrowRight, TrendingUp, AlertTriangle, Download, Table, Sparkles, ChevronDown, BarChart2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { LineageGraph } from './LineageGraph';
import { ChatPanel } from './ChatPanel';

function KPICard({ icon, title, value, subtitle, color, isActive, onClick }: {
  icon: React.ReactNode;
  title: string;
  value: number;
  subtitle: string;
  color: string;
  isActive: boolean;
  onClick: () => void;
}) {
  return (
    <Card 
      onClick={onClick}
      className={`cursor-pointer transition-all ${isActive ? 'ring-2 ring-primary border-transparent shadow-md' : 'hover:border-primary/50'}`}
    >
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className={`text-xs font-semibold uppercase tracking-wider ${isActive ? 'text-primary' : 'text-muted-foreground'}`}>{title}</CardTitle>
        <div className={`p-1.5 rounded-lg ${color}`}>
          {React.cloneElement(icon as React.ReactElement, { className: 'w-4 h-4' })}
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-3xl font-bold tracking-tight">{value}</p>
        <p className="text-xs text-muted-foreground mt-1">{subtitle}</p>
      </CardContent>
    </Card>
  );
}

function ComplexityBadge({ score }: { score: number }) {
  if (score >= 7) return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-rose-500/15 text-rose-400 border border-rose-500/20"><AlertTriangle className="w-3 h-3" />High</span>;
  if (score >= 4) return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-amber-500/15 text-amber-400 border border-amber-500/20"><TrendingUp className="w-3 h-3" />Medium</span>;
  return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/20">Low</span>;
}

export function InventoryView({ data, onViewDetails }: { data: any; onViewDetails: (dashboard: any) => void }) {
  const dashboardsCount = data.dashboards?.length || 0;
  const worksheetsCount = data.worksheets?.length || 0;
  const datasourcesCount = data.datasources?.length || 0;
  
  const allCalcFields: any[] = [];
  data.datasources?.forEach((ds: any) => {
    ds.calculated_fields?.forEach((cf: any) => {
      allCalcFields.push({ ...cf, dsName: ds.caption || ds.name });
    });
  });
  const calcFieldsCount = allCalcFields.length;

  const allTables: { name: string; dsName: string; columns: string[]; rows: string[][] }[] = [];
  data.datasources?.forEach((ds: any) => {
    ds.tables?.forEach((t: any) => {
      const cols = t.columns_preview || [];
      const rows = t.rows_preview || [];
      allTables.push({ name: t.name, dsName: ds.name, columns: cols, rows });
    });
  });
  const tablesCount = allTables.length;

  const workbookBaseName = data.source_file?.split(/[/\\]/).pop() || data.source_file;

  const [aiSummaries, setAiSummaries] = useState<{
    workbook_summary: string | null;
    workbook_domain: string | null;
    dashboards: { name: string; domain: string | null; complexity: number | null; summary: string | null }[];
  } | null>(null);

  useEffect(() => {
    if (!workbookBaseName) return;
    fetch(`${API_BASE_URL}/api/v1/agent/workbook-summary?workbook_name=${encodeURIComponent(workbookBaseName)}`)
      .then(r => r.json())
      .then(setAiSummaries)
      .catch(() => {});
  }, [workbookBaseName]);

  const exportCalculatedFieldsToJSON = () => {
    if (!data.datasources) return;
    const jsonData: any[] = [];
    data.datasources.forEach((ds: any) => {
      if (ds.calculated_fields) {
        ds.calculated_fields.forEach((cf: any) => {
          jsonData.push({
            "Datasource": ds.name,
            "Field Name": cf.name,
            "Data Type": cf.datatype || '',
            "Formula": cf.formula || ''
          });
        });
      }
    });
    
    const jsonString = JSON.stringify(jsonData, null, 2);
    const jsonContent = "data:text/json;charset=utf-8," + encodeURIComponent(jsonString);
    const link = document.createElement("a");
    link.setAttribute("href", jsonContent);
    link.setAttribute("download", `${data.source_file.replace('.twb', '')}_calculated_fields.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const exportWorksheetsToJSON = () => {
    if (!data.worksheets) return;
    const jsonData: any[] = [];
    
    data.worksheets.forEach((ws: any) => {
      jsonData.push({
        "Worksheet Name": ws.name || '',
        "Mark Type": ws.mark_type || 'Automatic',
        "Columns (X-Axis)": ws.columns ? ws.columns.join(', ') : '',
        "Rows (Y-Axis)": ws.rows ? ws.rows.join(', ') : ''
      });
    });
    
    const jsonString = JSON.stringify(jsonData, null, 2);
    const jsonContent = "data:text/json;charset=utf-8," + encodeURIComponent(jsonString);
    const link = document.createElement("a");
    link.setAttribute("href", jsonContent);
    link.setAttribute("download", `${data.source_file.replace('.twb', '').replace('.twbx', '')}_worksheets.json`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  const [activeTab, setActiveTab] = useState<'dashboards' | 'worksheets' | 'kpis' | 'calcFields' | 'tables'>('dashboards');
  const [selectedWorksheet, setSelectedWorksheet] = useState<string | null>(null);

  const allKPIs: any[] = [];
  if (aiSummaries?.dashboards) {
    aiSummaries.dashboards.forEach((d: any) => {
      if (d.kpis && Array.isArray(d.kpis)) {
        d.kpis.forEach((kpi: any) => {
          allKPIs.push({ ...kpi, dashboardName: d.name });
        });
      }
    });
  }
  return (
    <>
      <div className="w-full space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight text-foreground flex items-center gap-3">
            <LayoutDashboard className="w-6 h-6 text-primary" />
            Workbook Overview
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            Analyzing <strong className="text-foreground">{data.source_file}</strong>
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs px-3 py-1.5 rounded-full bg-primary/15 text-primary border border-primary/20 font-medium">
            Scan Complete
          </span>
        </div>
      </div>



      {/* KPI Row */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <KPICard
          icon={<LayoutDashboard />}
          title="Dashboards"
          value={dashboardsCount}
          subtitle="Total discovered"
          color="bg-blue-500/15 text-blue-400"
          isActive={activeTab === 'dashboards'}
          onClick={() => setActiveTab('dashboards')}
        />
        <KPICard
          icon={<Sparkles />}
          title="KPI"
          value={allKPIs.length}
          subtitle="AI Extracted KPIs"
          color="bg-indigo-500/15 text-indigo-400"
          isActive={activeTab === 'kpis'}
          onClick={() => setActiveTab('kpis')}
        />
        <KPICard
          icon={<FileSpreadsheet />}
          title="Worksheets"
          value={worksheetsCount}
          subtitle="Individual views"
          color="bg-emerald-500/15 text-emerald-400"
          isActive={activeTab === 'worksheets'}
          onClick={() => setActiveTab('worksheets')}
        />
        <KPICard
          icon={<Calculator />}
          title="Calculated Fields"
          value={calcFieldsCount}
          subtitle="Custom business logic"
          color="bg-purple-500/15 text-purple-400"
          isActive={activeTab === 'calcFields'}
          onClick={() => setActiveTab('calcFields')}
        />
        <KPICard
          icon={<Table />}
          title="Data Sources KPI"
          value={tablesCount}
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
              <span className="text-xs text-muted-foreground">{dashboardsCount} total</span>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            <div className="grid grid-cols-12 px-6 py-3 bg-muted/30 border-b border-border text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              <span className="col-span-10">Dashboard & AI Summary</span>
              <span className="col-span-2 text-right">Action</span>
            </div>
            <div className="divide-y divide-border">
              {data.dashboards?.map((db: any, idx: number) => {
                const aiDb = aiSummaries?.dashboards?.find((d: any) => d.name === db.name);
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
                                ⚙️ Governance Fallback
                              </span>
                            )
                          )}
                        </div>
                        {aiDb?.summary ? (
                          <p className="text-[11px] text-muted-foreground leading-relaxed pr-8">{aiDb.summary}</p>
                        ) : (
                          <p className="text-[11px] text-muted-foreground/40 italic">Run agents to generate</p>
                        )}
                      </div>
                    </div>
                    
                    <div className="col-span-2 flex justify-end pt-1">
                      <button
                        onClick={() => onViewDetails(db)}
                        className="flex items-center gap-1 px-3 py-1.5 bg-primary hover:bg-primary/90 text-primary-foreground rounded-lg text-xs font-medium transition-all opacity-0 group-hover:opacity-100 shadow-sm"
                      >
                        Details
                        <ArrowRight className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })}
              {(!data.dashboards || data.dashboards.length === 0) && (
                <div className="px-6 py-12 text-center text-muted-foreground text-sm">
                  No dashboards found in this workbook.
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
                <span className="text-xs text-muted-foreground">{worksheetsCount} total</span>
              </div>
            </CardHeader>
            <CardContent className="p-4">
              {data.worksheets?.length > 0 ? (
                <ul className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {data.worksheets.map((ws: any, idx: number) => {
                    const isSelected = selectedWorksheet === ws.name;
                    return (
                      <li key={idx} className={`rounded-lg border text-sm transition-all ${isSelected ? 'bg-primary/10 border-primary/40 shadow-sm' : 'bg-muted/40 border-border hover:bg-muted/80'}`}>
                        <div 
                          className="flex items-center gap-3 px-4 py-3 cursor-pointer"
                          onClick={() => setSelectedWorksheet(isSelected ? null : ws.name)}
                        >
                          <div className={`w-2 h-2 rounded-full flex-shrink-0 ${isSelected ? 'bg-primary' : 'bg-emerald-500'}`} />
                          <span className={`font-medium truncate ${isSelected ? 'text-primary' : 'text-foreground'}`}>{ws.name}</span>
                          <ChevronDown className={`w-4 h-4 ml-auto text-muted-foreground transition-transform duration-200 ${isSelected ? 'rotate-180' : ''}`} />
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
          
          {/* Worksheet Lineage */}
          <Card>
            <CardHeader className="border-b border-border pb-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Worksheet Lineage</CardTitle>
                <span className="text-xs text-muted-foreground">Connections to Dashboards</span>
              </div>
            </CardHeader>
            <CardContent className="p-6">
              <LineageGraph workbookName={workbookBaseName} viewType="worksheets" />
            </CardContent>
          </Card>
        </div>
      )}

      {/* TAB: KPIs */}
      {activeTab === 'kpis' && (
        <Card className="animate-in fade-in duration-300">
          <CardHeader className="border-b border-border pb-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base flex items-center gap-2">
                <Sparkles className="w-5 h-5 text-indigo-500" />
                Key Performance Indicators (LLM Extracted)
              </CardTitle>
              <span className="text-xs text-muted-foreground">{allKPIs.length} total</span>
            </div>
          </CardHeader>
          <CardContent className="p-6">
            {allKPIs.length > 0 ? (
              <div className="space-y-6">
                {allKPIs.map((kpi: any, idx: number) => (
                  <div key={idx} className="p-5 rounded-xl border border-indigo-500/20 bg-indigo-500/5 flex flex-col gap-3">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-2">
                        <h4 className="text-lg font-bold text-indigo-400">{kpi.name}</h4>
                        <span className="px-2 py-0.5 rounded text-[10px] bg-primary/10 text-primary border border-primary/20">
                          {kpi.dashboardName}
                        </span>
                      </div>
                      <span className="text-xs font-semibold px-2 py-1 rounded bg-slate-800 text-slate-300 border border-slate-700">
                        Confidence: {kpi.confidence}%
                      </span>
                    </div>
                    
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-2">
                      <div className="bg-background rounded-lg p-3 border border-border/50">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Source</p>
                        <p className="text-sm text-foreground/90">{kpi.source_description || 'Extracted from dashboard metadata.'}</p>
                      </div>
                      <div className="bg-background rounded-lg p-3 border border-border/50">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Calculation Logic</p>
                        <p className="text-sm text-foreground/90">{kpi.calculation_logic || 'Standard aggregation.'}</p>
                      </div>
                      <div className="bg-background rounded-lg p-3 border border-border/50">
                        <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-1">Definition</p>
                        <p className="text-sm text-foreground/90">{kpi.definition || 'Key business metric.'}</p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="text-center py-12">
                <Sparkles className="w-8 h-8 text-muted-foreground/30 mx-auto mb-3" />
                <p className="text-sm text-muted-foreground italic">No KPIs have been extracted yet or the AI summary is still generating.</p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* TAB: Calculated Fields */}
      {activeTab === 'calcFields' && (
        <Card className="animate-in fade-in duration-300">
          <CardHeader className="border-b border-border pb-4">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">Calculated Fields</CardTitle>
              <span className="text-xs text-muted-foreground">{calcFieldsCount} total</span>
            </div>
          </CardHeader>
          <CardContent className="p-4">
            {allCalcFields.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {allCalcFields.map((cf: any, idx: number) => (
                  <div key={idx} className="p-4 rounded-xl border border-border bg-muted/20 flex flex-col gap-2">
                    <div className="flex justify-between items-start gap-2">
                      <div className="flex items-center gap-2 text-purple-400 font-semibold">
                        <Calculator className="w-4 h-4" />
                        <span className="truncate">{cf.name}</span>
                      </div>
                      <span className="px-2 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-500 border border-amber-500/20 truncate max-w-[120px]">
                        {cf.dsName}
                      </span>
                    </div>
                    <code className="mt-2 text-xs text-muted-foreground break-all leading-relaxed whitespace-pre-wrap bg-background p-2 rounded border border-border/50">
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
                <span className="text-xs text-muted-foreground">{tablesCount} table{tablesCount !== 1 ? 's' : ''} · first 5 rows</span>
              </div>
            </CardHeader>
            <CardContent className="p-6">
              {allTables.length === 0 ? (
                <p className="text-sm text-muted-foreground italic text-center py-8">No physical tables detected in this workbook.</p>
              ) : (
                <div className="space-y-8">
                  {allTables.map((t, idx) => (
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
                          <p className="text-[10px] uppercase tracking-wider text-muted-foreground font-semibold mb-3">Column Schema <span className="text-muted-foreground/50 font-normal ml-1">· no data preview available (.twb without extract)</span></p>
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

          {/* Table Lineage Graph */}
          <Card>
            <CardHeader className="border-b border-border pb-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Table Lineage</CardTitle>
                <span className="text-xs text-muted-foreground">Joins and relationships</span>
              </div>
            </CardHeader>
            <CardContent className="p-6">
              <LineageGraph workbookName={workbookBaseName} viewType="tables" />
            </CardContent>
          </Card>
        </div>
      )}
    </div>

    {/* Floating Conversational BI Chat */}
    <ChatPanel workbookName={workbookBaseName} />
    </>
  );
}