import React from 'react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';
import { FileSpreadsheet, LayoutDashboard, Database, ArrowRight } from 'lucide-react';

export function WorkbookListView({ workbooks, onSelectWorkbook }: { workbooks: any[]; onSelectWorkbook: (wb: any) => void }) {
  
  if (!workbooks || workbooks.length === 0) return null;

  const totalDashboards = workbooks.reduce((acc, wb) => acc + (wb.dashboards?.length || 0), 0);
  const totalWorksheets = workbooks.reduce((acc, wb) => acc + (wb.worksheets?.length || 0), 0);
  const totalDatasources = workbooks.reduce((acc, wb) => acc + (wb.datasources?.length || 0), 0);

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-bottom-2 duration-300">
      
      {/* Global summary for the upload */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
        <Card className="bg-primary/5 border-primary/20">
          <CardContent className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-primary/20 flex items-center justify-center">
              <FileSpreadsheet className="w-5 h-5 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">Files Scanned</p>
              <h3 className="text-2xl font-bold">{workbooks.length}</h3>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-blue-500/10 flex items-center justify-center">
              <LayoutDashboard className="w-5 h-5 text-blue-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">Total Dashboards</p>
              <h3 className="text-2xl font-bold">{totalDashboards}</h3>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-emerald-500/10 flex items-center justify-center">
              <FileSpreadsheet className="w-5 h-5 text-emerald-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">Total Worksheets</p>
              <h3 className="text-2xl font-bold">{totalWorksheets}</h3>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 flex items-center gap-4">
            <div className="w-10 h-10 rounded-lg bg-amber-500/10 flex items-center justify-center">
              <Database className="w-5 h-5 text-amber-500" />
            </div>
            <div>
              <p className="text-sm font-medium text-muted-foreground">Total Datasources</p>
              <h3 className="text-2xl font-bold">{totalDatasources}</h3>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="pb-3 border-b border-border">
          <CardTitle>Parsed Workbooks (Files)</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="divide-y divide-border">
            {workbooks.map((wb, idx) => (
              <div 
                key={idx} 
                onClick={() => onSelectWorkbook(wb)}
                className="p-4 hover:bg-muted/30 transition-colors cursor-pointer flex items-center justify-between group"
              >
                <div className="flex items-center gap-4">
                  <div className="w-10 h-10 rounded-lg bg-secondary flex items-center justify-center">
                    <FileSpreadsheet className="w-5 h-5 text-secondary-foreground" />
                  </div>
                  <div>
                    <h3 className="text-sm font-bold text-foreground">{wb.source_file || `Workbook ${idx + 1}`}</h3>
                    <p className="text-xs text-muted-foreground mt-0.5">Tableau Version {wb.version || 'Unknown'}</p>
                  </div>
                </div>
                
                <div className="flex items-center gap-6">
                  <div className="flex gap-4 text-xs font-medium text-muted-foreground">
                    <span className="flex items-center gap-1.5 px-2 py-1 bg-muted rounded-md">
                      <LayoutDashboard className="w-3.5 h-3.5" />
                      {wb.dashboards?.length || 0}
                    </span>
                    <span className="flex items-center gap-1.5 px-2 py-1 bg-muted rounded-md">
                      <Database className="w-3.5 h-3.5" />
                      {wb.datasources?.length || 0}
                    </span>
                  </div>
                  <ArrowRight className="w-4 h-4 text-muted-foreground group-hover:text-primary transition-colors group-hover:translate-x-1" />
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
