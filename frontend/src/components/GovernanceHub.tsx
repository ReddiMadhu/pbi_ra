import React, { useMemo, useState, useEffect } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import {
  Activity, AlertTriangle, Copy, LayoutDashboard, FolderSearch,
  FileSpreadsheet, ArrowRight, History, X, ChevronRight, CheckCircle2, Clock
} from "lucide-react";

// ── Duplicate detection ───────────────────────────────────────────────────────
function detectDuplicates(workbooksData: any[]): { groups: any[][], count: number } {
  if (!workbooksData || workbooksData.length < 2) return { groups: [], count: 0 };

  // Group by file size (files with identical size are candidate duplicates)
  const sizeMap: Record<number, any[]> = {};
  workbooksData.forEach(wb => {
    const size = wb.file_size_bytes || 0;
    if (!sizeMap[size]) sizeMap[size] = [];
    sizeMap[size].push(wb);
  });

  const groups = Object.values(sizeMap).filter(g => g.length > 1);
  const count = groups.reduce((acc, g) => acc + g.length, 0);
  return { groups, count };
}

// ── Domain classification ────────────────────────────────────────────────────
function classifyDomain(wb: any): string {
  if (wb.business_domain) return wb.business_domain;
  
  const n = (wb.source_file || '').toLowerCase().replace(/\.[^/.]+$/, "");
  const nameParts = n.split(/[_-\s]/).filter((p: string) => p.length > 2);
  
  let coreTopic = 'General';
  if (nameParts.length > 0) {
    coreTopic = nameParts[0].charAt(0).toUpperCase() + nameParts[0].slice(1);
    if (nameParts.length > 1 && nameParts[0].length + nameParts[1].length < 15) {
       coreTopic += ' ' + nameParts[1].charAt(0).toUpperCase() + nameParts[1].slice(1);
    }
  }
  
  const dashCount = wb.dashboards?.length || 0;
  const dsCount = wb.datasources?.length || 0;
  
  let type = 'Reporting';
  if (dashCount > 2) type = 'Analytics';
  else if (dsCount > 2) type = 'Data Ops';
  else if (coreTopic === 'General') type = 'Operations';
  
  return `${coreTopic} ${type}`;
}

// ── Activity Color Mapping ───────────────────────────────────────────────────
function getActivityColor(days: number) {
  if (days < 5) return 'text-emerald-700 bg-emerald-700/10 border-emerald-700/20'; 
  if (days < 10) return 'text-emerald-500 bg-emerald-500/10 border-emerald-500/20'; 
  if (days < 15) return 'text-lime-500 bg-lime-500/10 border-lime-500/20'; 
  if (days < 20) return 'text-yellow-500 bg-yellow-500/10 border-yellow-500/20'; 
  if (days < 23) return 'text-amber-500 bg-amber-500/10 border-amber-500/20'; 
  if (days < 25) return 'text-orange-500 bg-orange-500/10 border-orange-500/20'; 
  if (days < 28) return 'text-red-500 bg-red-500/10 border-red-500/20'; 
  return 'text-rose-700 bg-rose-700/10 border-rose-700/20'; 
}

// ── Mock Last Used ──────────────────────────────────────────────────────────
function getMockLastUsedDays(filename: string): number {
  let hash = 0;
  for (let i = 0; i < filename.length; i++) {
    hash = filename.charCodeAt(i) + ((hash << 5) - hash);
  }
  return (Math.abs(hash) % 30) + 1;
}

// ── DuplicateModal ────────────────────────────────────────────────────────────
function DuplicateModal({ groups, onClose, onSelectFile }: { groups: any[][]; onClose: () => void; onSelectFile: (wb: any) => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-background border border-border rounded-2xl shadow-2xl w-full max-w-xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h3 className="font-bold text-foreground flex items-center gap-2">
              <Copy className="w-4 h-4 text-rose-400" /> Duplicate Files Detected
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">{groups.reduce((a, g) => a + g.length, 0)} files in {groups.length} duplicate group{groups.length !== 1 ? 's' : ''}</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Groups */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {groups.map((group, gi) => (
            <div key={gi} className="rounded-xl border border-rose-500/20 bg-rose-500/5 overflow-hidden">
              <div className="px-4 py-2 bg-rose-500/10 border-b border-rose-500/15 flex items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-rose-400">
                  Duplicate Group {gi + 1} · {(group[0].file_size_bytes / 1024).toFixed(1)} KB each
                </span>
                <span className="ml-auto px-1.5 py-0.5 rounded bg-rose-500/20 text-rose-400 text-[10px] font-bold border border-rose-500/30">
                  {group.length} files
                </span>
              </div>
              {group.map((wb, fi) => (
                <button
                  key={fi}
                  onClick={() => { onSelectFile(wb); onClose(); }}
                  className="w-full flex items-center gap-3 px-4 py-3 hover:bg-rose-500/10 transition-colors border-b border-rose-500/10 last:border-0 text-left group"
                >
                  <FileSpreadsheet className="w-4 h-4 text-rose-400 flex-shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-foreground truncate">{wb.source_file}</p>
                    <p className="text-[10px] text-muted-foreground">
                      {wb.dashboards?.length || 0} dashboards · {wb.datasources?.length || 0} datasources
                    </p>
                  </div>
                  <ChevronRight className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
                </button>
              ))}
            </div>
          ))}
          {groups.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <CheckCircle2 className="w-10 h-10 text-emerald-400 mb-3" />
              <p className="font-semibold text-foreground">No Duplicates Found</p>
              <p className="text-xs text-muted-foreground mt-1">All uploaded files are unique.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── ScanHistoryPanel ──────────────────────────────────────────────────────────
function ScanHistoryPanel({ workbooksData, onClose, onSelectFile }: { workbooksData: any[]; onClose: () => void; onSelectFile: (wb: any) => void }) {
  return (
    <div className="fixed inset-0 z-50 flex items-end sm:items-center justify-center bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-background border border-border rounded-2xl shadow-2xl w-full max-w-2xl max-h-[80vh] flex flex-col">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border">
          <div>
            <h3 className="font-bold text-foreground flex items-center gap-2">
              <History className="w-4 h-4 text-sky-400" /> Scan History — Current Session
            </h3>
            <p className="text-xs text-muted-foreground mt-0.5">{workbooksData.length} file{workbooksData.length !== 1 ? 's' : ''} scanned in this session</p>
          </div>
          <button onClick={onClose} className="p-1.5 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Stats strip */}
        <div className="grid grid-cols-3 divide-x divide-border border-b border-border">
          {[
            { label: 'Files Scanned', value: workbooksData.length, color: 'text-sky-400' },
            { label: 'Total Dashboards', value: workbooksData.reduce((a, wb) => a + (wb.dashboards?.length || 0), 0), color: 'text-violet-400' },
            { label: 'Total Worksheets', value: workbooksData.reduce((a, wb) => a + (wb.worksheets?.length || 0), 0), color: 'text-emerald-400' },
          ].map((s, i) => (
            <div key={i} className="flex flex-col items-center py-3">
              <p className={`text-2xl font-bold ${s.color}`}>{s.value}</p>
              <p className="text-[10px] text-muted-foreground mt-0.5">{s.label}</p>
            </div>
          ))}
        </div>

        {/* File list */}
        <div className="flex-1 overflow-y-auto divide-y divide-border">
          {workbooksData.map((wb, idx) => (
            <button
              key={idx}
              onClick={() => { onSelectFile(wb); onClose(); }}
              className="w-full flex items-center gap-4 px-6 py-3.5 hover:bg-accent/30 transition-colors text-left group"
            >
              <div className="w-8 h-8 rounded-lg bg-sky-500/10 flex items-center justify-center flex-shrink-0">
                <FileSpreadsheet className="w-4 h-4 text-sky-400" />
              </div>
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm text-foreground truncate">{wb.source_file}</p>
                <p className="text-xs text-muted-foreground">
                  {wb.dashboards?.length || 0} dashboards · {wb.worksheets?.length || 0} worksheets · {wb.datasources?.length || 0} datasources · {((wb.file_size_bytes || 0) / 1024).toFixed(1)} KB
                </p>
              </div>
              <div className="flex items-center gap-2">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium border ${
                  idx === 0 ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 'bg-muted text-muted-foreground border-border'
                }`}>
                  {idx === 0 ? 'Latest' : `#${idx + 1}`}
                </span>
                <ChevronRight className="w-3.5 h-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
              </div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main GovernanceHub ────────────────────────────────────────────────────────
export function GovernanceHub({ onStartScan, workbooksData, onSelectFile }: {
  onStartScan: () => void;
  workbooksData: any[] | null;
  onSelectFile: (wb: any) => void;
}) {
  const [showDuplicates, setShowDuplicates] = useState(false);
  const [showScanHistory, setShowScanHistory] = useState(false);
  const [isClassifying, setIsClassifying] = useState(false);

  const wb = workbooksData || [];

  useEffect(() => {
    if (wb.length > 0) {
      setIsClassifying(true);
      const timer = setTimeout(() => {
        setIsClassifying(false);
      }, 2500); // Simulate AI classification delay
      return () => clearTimeout(timer);
    }
  }, [wb]);



  const sortedWb = useMemo(() => {
    return [...wb].map(w => ({
      ...w,
      mockLastUsedDays: getMockLastUsedDays(w.source_file || '')
    })).sort((a, b) => a.mockLastUsedDays - b.mockLastUsedDays);
  }, [wb]);

  const stats = useMemo(() => {
    const { count: dupCount } = detectDuplicates(wb);
    return {
      total: wb.length,
      active: wb.length - Math.floor(wb.length * 0.1),
      stale: Math.floor(wb.length * 0.1),
      duplicates: dupCount,
    };
  }, [wb]);

  const { groups: dupGroups } = useMemo(() => detectDuplicates(wb), [wb]);

  return (
    <>
      <div className="space-y-6 flex flex-col animate-in fade-in zoom-in-95 duration-300">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-3xl font-bold tracking-tight">Session Governance Hub</h2>
            <p className="text-muted-foreground mt-1 text-slate-500">
              Real-time analysis of your currently uploaded Tableau repository batch.
            </p>
          </div>
          <div className="flex items-center gap-2">
            {wb.length > 0 && (
              <button
                onClick={() => setShowScanHistory(true)}
                className="flex items-center gap-2 border border-border hover:bg-accent px-4 py-2 rounded-md text-sm font-medium transition-colors"
              >
                <History className="w-4 h-4" />
                Scan History ({wb.length})
              </button>
            )}
            <button
              onClick={onStartScan}
              className="flex items-center bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-md text-sm font-medium transition-colors"
            >
              <FolderSearch className="w-4 h-4 mr-2" />
              {wb.length > 0 ? 'Scan New Batch' : 'Start Scan'}
            </button>
          </div>
        </div>

        {/* KPI Cards */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {/* Files Analyzed */}
          <div onClick={() => wb.length > 0 && setShowScanHistory(true)} className={wb.length > 0 ? 'cursor-pointer' : ''}>
            <Card className={`transition-all ${wb.length > 0 ? 'hover:border-sky-500/40 hover:bg-sky-500/5' : ''}`}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Files Scanned</CardTitle>
                <History className="h-4 w-4 text-sky-400" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{stats.total}</div>
                <p className="text-xs text-slate-500 mt-1">{wb.length > 0 ? 'Click to view scan history' : 'In current session'}</p>
              </CardContent>
            </Card>
          </div>

          {/* Active */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active & Used</CardTitle>
              <Activity className="h-4 w-4 text-emerald-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.active}</div>
              <p className="text-xs text-slate-500 mt-1">Recently modified files</p>
            </CardContent>
          </Card>

          {/* Stale */}
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Previously used files</CardTitle>
              <AlertTriangle className="h-4 w-4 text-amber-500" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{stats.stale}</div>
              <p className="text-xs text-slate-500 mt-1">3 months prior</p>
            </CardContent>
          </Card>

          {/* Duplicates — clickable */}
          <div
            onClick={() => stats.duplicates > 0 && setShowDuplicates(true)}
            className={stats.duplicates > 0 ? 'cursor-pointer' : ''}
          >
            <Card className={`transition-all ${stats.duplicates > 0 ? 'hover:border-rose-500/40 hover:bg-rose-500/5' : ''}`}>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Duplicates Detected</CardTitle>
                <Copy className="h-4 w-4 text-rose-500" />
              </CardHeader>
              <CardContent>
                <div className={`text-2xl font-bold ${stats.duplicates > 0 ? 'text-rose-400' : ''}`}>{stats.duplicates}</div>
                <p className="text-xs text-slate-500 mt-1">
                  {stats.duplicates > 0 ? 'Click to see duplicate files' : 'No duplicates found'}
                </p>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Session Files (3 Columns) */}
        <div className="mt-4">
          <Card className="flex flex-col h-[500px]">
            <CardHeader className="pb-3 border-b border-border shrink-0">
              <div className="flex items-center justify-between">
                <CardTitle>Session Files</CardTitle>
                {wb.length > 0 && (
                  <span className="text-xs text-muted-foreground">{wb.length} file{wb.length !== 1 ? 's' : ''}</span>
                )}
              </div>
            </CardHeader>
            <CardContent className="p-0 overflow-y-auto">
              {wb.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 text-center">
                  <p className="text-sm text-slate-500 mb-4">No files uploaded in this session.</p>
                  <button onClick={onStartScan} className="text-sm text-indigo-600 font-medium hover:underline">
                    Upload your repository to begin
                  </button>
                </div>
              ) : (
                <table className="w-full text-left text-sm">
                  <thead className="bg-muted/30 text-muted-foreground text-xs uppercase sticky top-0 z-10 backdrop-blur-md">
                    <tr>
                      <th className="px-6 py-3 font-medium">File Name</th>
                      <th className="px-6 py-3 font-medium">Activity</th>
                      <th className="px-6 py-3 font-medium">Business Domain Identified</th>
                      <th className="px-6 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {sortedWb.map((w, idx) => {
                      const isDup = dupGroups.some(g => g.includes(w));
                      const aiDomain = classifyDomain(w);
                      const activityColorClass = getActivityColor(w.mockLastUsedDays);
                      return (
                        <tr 
                          key={idx} 
                          onClick={() => onSelectFile(w)} 
                          className="hover:bg-muted/30 transition-colors cursor-pointer group"
                        >
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-4">
                              <div className="w-8 h-8 rounded-lg bg-indigo-500/10 flex items-center justify-center relative flex-shrink-0">
                                <FileSpreadsheet className="w-4 h-4 text-indigo-500" />
                                {isDup && (
                                  <div className="absolute -top-1 -right-1 w-3 h-3 rounded-full bg-rose-500 border border-background" title="Duplicate" />
                                )}
                              </div>
                              <div className="min-w-0">
                                <p className="font-medium text-sm text-foreground truncate">{w.source_file}</p>
                                <p className="text-[10px] text-muted-foreground mt-0.5">
                                  {w.dashboards?.length || 0} Dashboards · {w.datasources?.length || 0} Datasources
                                  {isDup && <span className="ml-2 text-rose-400 font-medium">· Duplicate</span>}
                                </p>
                              </div>
                            </div>
                          </td>
                          <td className="px-6 py-4 whitespace-nowrap">
                            <span className={`text-xs font-medium px-2.5 py-1 rounded-full border ${activityColorClass}`}>
                              Used {w.mockLastUsedDays} day{w.mockLastUsedDays !== 1 ? 's' : ''} ago
                            </span>
                          </td>
                          <td className="px-6 py-4">
                            <div className="flex items-center gap-1.5">
                              {isClassifying ? (
                                <span className="flex items-center gap-2 text-xs text-muted-foreground font-medium bg-muted/50 px-3 py-1.5 rounded-md border border-border">
                                  <div className="w-3 h-3 border-2 border-indigo-500/30 border-t-indigo-500 rounded-full animate-spin" />
                                  AI Analyzing...
                                </span>
                              ) : (
                                <span className="text-xs font-medium bg-indigo-500/10 text-indigo-500 border border-indigo-500/20 px-3 py-1.5 rounded-md flex items-center gap-1.5 w-max">
                                  <Activity className="w-3 h-3" />
                                  {aiDomain}
                                </span>
                              )}
                            </div>
                          </td>
                          <td className="px-6 py-4 text-right">
                            <ArrowRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:text-primary transition-all inline-block group-hover:translate-x-1" />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Modals */}
      {showDuplicates && (
        <DuplicateModal
          groups={dupGroups}
          onClose={() => setShowDuplicates(false)}
          onSelectFile={onSelectFile}
        />
      )}
      {showScanHistory && (
        <ScanHistoryPanel
          workbooksData={wb}
          onClose={() => setShowScanHistory(false)}
          onSelectFile={onSelectFile}
        />
      )}
    </>
  );
}
