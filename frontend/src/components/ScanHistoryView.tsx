import React from 'react';
import { Activity, FileSpreadsheet, LayoutDashboard, Database, Calculator, Table, ChevronRight, FolderSearch } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

export function ScanHistoryView({
  workbooksData,
  onSelectFile,
  onStartScan,
}: {
  workbooksData: any[] | null;
  onSelectFile: (wb: any) => void;
  onStartScan: () => void;
}) {
  const wb = workbooksData || [];

  const totalDashboards = wb.reduce((a, w) => a + (w.dashboards?.length || 0), 0);
  const totalWorksheets = wb.reduce((a, w) => a + (w.worksheets?.length || 0), 0);
  const totalDatasources = wb.reduce((a, w) => a + (w.datasources?.length || 0), 0);
  const totalCalcFields = wb.reduce((a, w) =>
    a + (w.datasources?.reduce((b: number, ds: any) => b + (ds.calculated_fields?.length || 0), 0) || 0), 0);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-300">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-3">
            <Activity className="w-6 h-6 text-primary" />
            Scan History
          </h2>
          <p className="text-sm text-muted-foreground mt-1">
            {wb.length > 0
              ? `${wb.length} file${wb.length !== 1 ? 's' : ''} scanned in this session`
              : 'No scans yet in this session'}
          </p>
        </div>
        <button
          onClick={onStartScan}
          className="flex items-center gap-2 bg-indigo-600 hover:bg-indigo-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors"
        >
          <FolderSearch className="w-4 h-4" />
          New Scan
        </button>
      </div>

      {wb.length === 0 ? (
        /* Empty state */
        <div className="flex flex-col items-center justify-center py-24 text-center border-2 border-dashed border-border rounded-2xl">
          <div className="w-16 h-16 rounded-2xl bg-muted flex items-center justify-center mb-4">
            <Activity className="w-8 h-8 text-muted-foreground" />
          </div>
          <h3 className="font-semibold text-foreground mb-1">No scans yet</h3>
          <p className="text-sm text-muted-foreground max-w-xs mb-6">
            Upload Tableau workbook files to begin. Each uploaded batch will appear here.
          </p>
          <button
            onClick={onStartScan}
            className="flex items-center gap-2 bg-primary text-primary-foreground px-5 py-2.5 rounded-xl text-sm font-medium hover:bg-primary/90 transition-colors"
          >
            <FolderSearch className="w-4 h-4" />
            Upload Files
          </button>
        </div>
      ) : (
        <>
          {/* Aggregated session KPIs */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            {[
              { icon: FileSpreadsheet, label: 'Files Scanned',     value: wb.length,        color: 'bg-sky-500/15 text-sky-400' },
              { icon: LayoutDashboard, label: 'Total Dashboards',  value: totalDashboards,   color: 'bg-violet-500/15 text-violet-400' },
              { icon: Database,        label: 'Total Datasources', value: totalDatasources,  color: 'bg-amber-500/15 text-amber-400' },
              { icon: Calculator,      label: 'Calc Fields',       value: totalCalcFields,   color: 'bg-emerald-500/15 text-emerald-400' },
            ].map(({ icon: Icon, label, value, color }) => (
              <Card key={label}>
                <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                  <CardTitle className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">{label}</CardTitle>
                  <div className={`p-1.5 rounded-lg ${color}`}>
                    <Icon className="w-4 h-4" />
                  </div>
                </CardHeader>
                <CardContent>
                  <p className="text-3xl font-bold tracking-tight">{value}</p>
                  <p className="text-xs text-muted-foreground mt-1">Across all scanned files</p>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Session Governance Hub (existing) */}
          <div className="mt-2">
            <p className="text-xs font-semibold uppercase tracking-widest text-muted-foreground mb-4 px-1">
              Session Governance Hub
            </p>
          </div>

          {/* File-by-file scan list */}
          <Card>
            <CardHeader className="border-b border-border pb-4">
              <div className="flex items-center justify-between">
                <CardTitle className="text-base">Scanned Files</CardTitle>
                <span className="text-xs text-muted-foreground">{wb.length} total</span>
              </div>
            </CardHeader>
            <CardContent className="p-0">
              {/* Table header */}
              <div className="grid grid-cols-12 px-6 py-3 bg-muted/30 border-b border-border text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                <span className="col-span-5">File Name</span>
                <span className="col-span-2 text-center">Dashboards</span>
                <span className="col-span-2 text-center">Worksheets</span>
                <span className="col-span-2 text-center">Size</span>
                <span className="col-span-1 text-right"></span>
              </div>
              <div className="divide-y divide-border">
                {wb.map((w, idx) => (
                  <button
                    key={idx}
                    onClick={() => onSelectFile(w)}
                    className="w-full grid grid-cols-12 px-6 py-4 items-center hover:bg-accent/30 transition-colors group text-left"
                  >
                    <div className="col-span-5 flex items-center gap-3">
                      <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center flex-shrink-0">
                        <FileSpreadsheet className="w-4 h-4 text-primary" />
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium text-sm text-foreground truncate">{w.source_file}</p>
                        <p className="text-xs text-muted-foreground">{w.datasources?.length || 0} datasource{(w.datasources?.length || 0) !== 1 ? 's' : ''}</p>
                      </div>
                    </div>
                    <div className="col-span-2 text-center">
                      <span className="text-sm font-semibold text-foreground">{w.dashboards?.length || 0}</span>
                    </div>
                    <div className="col-span-2 text-center">
                      <span className="text-sm font-semibold text-foreground">{w.worksheets?.length || 0}</span>
                    </div>
                    <div className="col-span-2 text-center">
                      <span className="text-xs text-muted-foreground">
                        {w.file_size_bytes ? `${(w.file_size_bytes / 1024).toFixed(1)} KB` : '—'}
                      </span>
                    </div>
                    <div className="col-span-1 flex justify-end">
                      <ChevronRight className="w-4 h-4 text-muted-foreground opacity-0 group-hover:opacity-100 group-hover:text-primary transition-all group-hover:translate-x-0.5" />
                    </div>
                  </button>
                ))}
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
