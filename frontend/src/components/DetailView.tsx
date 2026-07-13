import { API_BASE_URL } from '@/config';
import React from 'react';
import { ArrowLeft, Layers, Database, Calculator, GitBranch, ChevronDown, BarChart2, Sparkles, Info } from 'lucide-react';
import { LineageGraph } from './LineageGraph';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { OntologyScoreBadge, OntologyKPIInventory } from './OntologyScoreBadge';
import { Button } from './ui/button';

export function DetailView({
  dashboard,
  workbookData,
  onBack,
  onResolveKpis,
}: {
  dashboard: any;
  workbookData: any;
  onBack: () => void;
  onResolveKpis?: (reportId: number) => void;
}) {
  const [selectedWorksheet, setSelectedWorksheet] = React.useState<string | null>(null);
  const [aiSummaries, setAiSummaries] = React.useState<any>(null);
  const [ontologyInventory, setOntologyInventory] = React.useState<OntologyKPIInventory | null>(null);

  const workbookBaseName = workbookData?.source_file?.split(/[/\\]/).pop() || workbookData?.source_file;

  React.useEffect(() => {
    if (!workbookBaseName) return;
    fetch(`${API_BASE_URL}/api/v1/agent/workbook-summary?workbook_name=${encodeURIComponent(workbookBaseName)}`)
      .then(r => r.json())
      .then(setAiSummaries)
      .catch(() => {});
  }, [workbookBaseName]);

  React.useEffect(() => {
    if (!dashboard?.id) return;
    fetch(`${API_BASE_URL}/api/v1/ontology/reports/${dashboard.id}/kpis`)
      .then((r) => r.json())
      .then((data) => {
        if (data?.total > 0) setOntologyInventory(data);
      })
      .catch(() => {});
  }, [dashboard?.id]);

  const aiDb = aiSummaries?.dashboards?.find((d: any) => d.name === dashboard.name);

  const relatedWorksheets = dashboard.worksheets || [];
  const datasources = workbookData.datasources || [];
  const totalCalcFields = datasources.reduce((acc: number, ds: any) => acc + (ds.calculated_fields?.length || 0), 0);

  return (
    <div className="w-full space-y-6 animate-in fade-in slide-in-from-right-8 duration-400">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">{dashboard.name}</h2>
          <p className="text-sm text-muted-foreground mt-1">Dashboard Metadata · Lineage · Governance Analysis</p>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <span className="px-3 py-1.5 text-xs font-semibold rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/20">
            {relatedWorksheets.length} Worksheets
          </span>
          <span className="px-3 py-1.5 text-xs font-semibold rounded-full bg-purple-500/15 text-purple-400 border border-purple-500/20">
            {totalCalcFields} Calc Fields
          </span>
        </div>
      </div>

      {/* AI Summary Card */}
      <Card className="border-primary/20 bg-primary/5 animate-in fade-in duration-500">
        <CardContent className="pt-4 pb-4 flex items-start gap-4">
          <div className="w-9 h-9 rounded-xl bg-primary/15 flex items-center justify-center flex-shrink-0 mt-0.5">
            <Sparkles className="w-5 h-5 text-primary" />
          </div>
          <div className="flex-1">
            <div className="flex items-center gap-2 mb-1.5 flex-wrap">
              <p className="text-xs font-bold uppercase tracking-wider text-primary">AI Dashboard Summary</p>
              {aiDb?.domain && (
                <span className="px-2 py-0.5 rounded-full bg-primary/15 text-primary text-[10px] font-bold border border-primary/20">
                  {aiDb.domain}
                </span>
              )}
              {aiDb?.summary && (
                aiDb.is_real_ai ? (
                  <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-[9px] font-bold border border-emerald-500/20 uppercase tracking-wider flex items-center gap-1">
                    <Sparkles className="w-2.5 h-2.5" /> Live AI Summary
                  </span>
                ) : (
                  <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 text-[9px] font-bold border border-amber-500/20 uppercase tracking-wider flex items-center gap-1">
                    ⚙️ Governance Fallback
                  </span>
                )
              )}
              {aiDb?.complexity != null && (
                <span className="px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 text-[10px] font-bold border border-slate-700 ml-auto">
                  Complexity: {aiDb.complexity}/10
                </span>
              )}
            </div>
            {aiDb?.summary ? (
              <p className="text-sm text-muted-foreground leading-relaxed">{aiDb.summary}</p>
            ) : (
              <p className="text-sm text-muted-foreground/50 italic flex items-center gap-2">
                <Info className="w-3.5 h-3.5" />
                AI summary not yet generated — parse the workbook to generate insights.
              </p>
            )}
          </div>
          <div className="mt-3 flex items-center gap-3 flex-wrap">
            <OntologyScoreBadge inventory={ontologyInventory} compact />
            {onResolveKpis && (ontologyInventory?.ambiguous || ontologyInventory?.not_found) ? (
              <Button variant="outline" size="sm" onClick={() => onResolveKpis(dashboard.id)}>
                Resolve KPIs
              </Button>
            ) : null}
          </div>
        </CardContent>
      </Card>

      {/* Two Column Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Worksheets & Selected Worksheet Details */}
        <Card className="flex flex-col h-[500px]">
          <CardHeader className="border-b border-border pb-4 shrink-0">
            <CardTitle className="text-sm flex items-center gap-2">
              <Layers className="w-4 h-4 text-primary" />
              Included Worksheets
              <span className="ml-auto text-xs text-muted-foreground font-normal">{relatedWorksheets.length} total</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 overflow-y-auto flex-1">
            {relatedWorksheets.length > 0 ? (
              <ul className="space-y-2 pr-1">
                {relatedWorksheets.map((ws: string, idx: number) => {
                  const isSelected = selectedWorksheet === ws;
                  const wsMeta = workbookData.worksheets?.find((w: any) => w.name === ws);
                  
                  return (
                    <li key={idx} className={`rounded-lg border text-sm transition-all ${isSelected ? 'bg-primary/10 border-primary/40 shadow-sm' : 'bg-muted/40 border-border hover:bg-muted/80'}`}>
                      <div 
                        className="flex items-center gap-3 px-3 py-2.5 cursor-pointer"
                        onClick={() => setSelectedWorksheet(isSelected ? null : ws)}
                      >
                        <div className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${isSelected ? 'bg-primary' : 'bg-emerald-500'}`} />
                        <span className={`font-medium truncate ${isSelected ? 'text-primary' : 'text-foreground'}`}>{ws}</span>
                        {wsMeta?.mark_type && (
                          <span className="ml-2 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/10 text-amber-400 border border-amber-500/20 font-medium shrink-0">{wsMeta.mark_type}</span>
                        )}
                        <ChevronDown className={`w-4 h-4 ml-auto text-muted-foreground transition-transform duration-200 ${isSelected ? 'rotate-180' : ''}`} />
                      </div>
                      
                      {isSelected && wsMeta && (
                        <div className="px-3 pb-3 pt-2 border-t border-primary/10 bg-background/50 rounded-b-lg text-xs animate-in slide-in-from-top-2 duration-200">
                          <div className="mb-3">
                            <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">Visual Type</span>
                            <span className="font-medium text-amber-400 flex items-center gap-1.5">
                              <BarChart2 className="w-3.5 h-3.5"/>
                              {wsMeta.mark_type || 'Automatic'}
                            </span>
                          </div>
                          
                          <div className="space-y-2.5">
                            <div>
                              <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">Axis</span>
                              <div className="flex flex-wrap gap-1.5">
                                {(() => {
                                  const axes = [...(wsMeta.columns || []), ...(wsMeta.rows || [])];
                                  return axes.length > 0 ? axes.map((a: string, i: number) => (
                                    <span key={i} className="px-1.5 py-0.5 bg-blue-500/15 text-blue-400 border border-blue-500/20 rounded font-mono">{a}</span>
                                  )) : <span className="text-muted-foreground italic text-xs">None</span>;
                                })()}
                              </div>
                            </div>
                            
                            <div>
                              <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">Value</span>
                              <div className="flex flex-wrap gap-1.5">
                                {wsMeta.used_calculated_fields?.length > 0 ? wsMeta.used_calculated_fields.map((v: string, i: number) => (
                                  <span key={i} className="px-1.5 py-0.5 bg-emerald-500/15 text-emerald-400 border border-emerald-500/20 rounded font-mono">{v}</span>
                                )) : <span className="text-muted-foreground italic text-xs">None</span>}
                              </div>
                            </div>
                            
                            <div>
                              <span className="text-muted-foreground block mb-1 text-[10px] uppercase tracking-wider font-semibold">Filter</span>
                              <div className="flex flex-wrap gap-1.5">
                                {wsMeta.filters_and_marks?.length > 0 ? wsMeta.filters_and_marks.map((f: string, i: number) => (
                                  <span key={i} className="px-1.5 py-0.5 bg-slate-500/15 text-slate-400 border border-slate-500/20 rounded font-mono">{f}</span>
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
              <p className="text-sm text-muted-foreground italic py-4 text-center">No worksheets detected in this dashboard.</p>
            )}
          </CardContent>
        </Card>

        {/* Datasources */}
        <Card className="flex flex-col h-[500px]">
          <CardHeader className="border-b border-border pb-4 shrink-0">
            <CardTitle className="text-sm flex items-center gap-2">
              <Database className="w-4 h-4 text-primary" />
              Underlying Data Sources
              <span className="ml-auto text-xs text-muted-foreground font-normal">{datasources.length} total</span>
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4 overflow-y-auto flex-1">
            {datasources.length > 0 ? (
              <div className="space-y-4">
                {datasources.map((ds: any, idx: number) => {
                  const wsMeta = selectedWorksheet ? workbookData.worksheets?.find((w: any) => w.name === selectedWorksheet) : null;
                  const usedCalcs = wsMeta?.used_calculated_fields || [];
                  
                  let fieldsToShow = ds.calculated_fields || [];
                  if (selectedWorksheet) {
                    fieldsToShow = fieldsToShow.filter((cf: any) => usedCalcs.includes(cf.name));
                  }

                  return (
                    <div key={idx}>
                      <div className="flex items-center gap-2 mb-2">
                        <Database className="w-3.5 h-3.5 text-amber-400" />
                        <h4 className="text-sm font-semibold text-amber-400 truncate">{ds.caption || ds.name}</h4>
                      </div>
                      
                      <div className="pl-4 border-l border-border space-y-1.5">
                        <p className="text-xs text-muted-foreground flex items-center gap-1.5 mb-2">
                          <Calculator className="w-3 h-3" />
                          {fieldsToShow.length} {selectedWorksheet ? 'Calculated Fields Used' : 'Calculated Fields'}
                        </p>
                        
                        {fieldsToShow.length > 0 ? (
                          <div className="space-y-2">
                            {fieldsToShow.map((cf: any, cIdx: number) => (
                              <div key={cIdx} className={`p-2.5 rounded-lg border text-xs ${selectedWorksheet ? 'bg-emerald-500/10 border-emerald-500/20' : 'bg-muted/40 border-border'}`}>
                                <span className={`font-semibold block mb-1 truncate ${selectedWorksheet ? 'text-emerald-400' : 'text-foreground'}`}>{cf.name}</span>
                                <code className="text-muted-foreground break-all leading-relaxed whitespace-pre-wrap">{cf.formula || ''}</code>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-xs text-muted-foreground italic py-1">No calculated fields from this source are used in the selected worksheet.</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground italic py-4 text-center">No datasources detected.</p>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Lineage Graph */}
      <Card>
        <CardHeader className="border-b border-border pb-4">
          <CardTitle className="text-sm flex items-center gap-2">
            <GitBranch className="w-4 h-4 text-primary" />
            Data Lineage Graph
          </CardTitle>
          <p className="text-xs text-muted-foreground mt-0.5">Interactive view of data flow from sources through to this dashboard</p>
        </CardHeader>
        <CardContent className="p-4">
          <LineageGraph dashboardName={dashboard.name} />
        </CardContent>
      </Card>
    </div>
  );
}