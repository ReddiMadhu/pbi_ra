import { useState, useEffect } from 'react';
import { UploadArea } from './components/UploadArea';
import { InventoryView } from './components/InventoryView';
import { DetailView } from './components/DetailView';
import { Layout } from './components/Layout';
import { LandscapeView } from './components/LandscapeView';
import { BIAssistView } from './components/BIAssistView';
import { BusinessAreasView } from './components/BusinessAreasView';
import { AreaDetailView } from './components/AreaDetailView';
import { DashboardOverviewView } from './components/DashboardOverviewView';
import { KPIDashboardGraph } from './components/KPIDashboardGraph';
import { RecommendationsView } from './components/RecommendationsView';
import { OntologyBankView } from './components/OntologyBankView';
type View = 'hub' | 'upload' | 'inventory' | 'overview' | 'detail' | 'landscape' | 'bi_assist' | 'areas' | 'areaDetail' | 'kpiGraph' | 'recommendations' | 'ontology';
function App() {
  const [currentView, setCurrentView] = useState<View>('upload');
  const [selectedLOBs, setSelectedLOBs] = useState<string[]>([]);
  const [selectedUserGroups, setSelectedUserGroups] = useState<string[]>([]);
  
  // State for the 3 tiers
  const [workbooksData, setWorkbooksData] = useState<any[] | null>(null); // Level 1
  const [selectedWorkbook, setSelectedWorkbook] = useState<any>(null);    // Level 2
  const [selectedDashboard, setSelectedDashboard] = useState<any>(null);  // Level 3
  const [selectedAreaId, setSelectedAreaId] = useState<string | null>(null); // Level 2 (Area)
  const [inventoryBackView, setInventoryBackView] = useState<View>('areas');
  const [requestedDashboardsForGraph, setRequestedDashboardsForGraph] = useState<string>('');
  const [recommendationsData, setRecommendationsData] = useState<any>(null);
  const [ontologyFilterReportId, setOntologyFilterReportId] = useState<string | undefined>();
  // Handle global cross-component dashboard navigation from ChatPanel
  useEffect(() => {
    const handleNav = (e: Event) => {
      const customEvent = e as CustomEvent;
      const rawWbName = customEvent.detail.workbook;
      const targetWbName = decodeURIComponent(rawWbName).trim();
      
      const wbMatch = workbooksData?.find(w => 
        w.source_file === targetWbName || 
        w.source_file?.toLowerCase() === targetWbName.toLowerCase()
      );
      
      if (wbMatch) {
        setInventoryBackView(currentView);
        setSelectedWorkbook(wbMatch);
        setSelectedDashboard(null);
        setCurrentView('inventory');
      } else {
        alert(`Sorry, I couldn't navigate to "${targetWbName}". Make sure the file is uploaded in your current session.`);
        console.warn(`Could not find workbook: ${targetWbName} in current session. Available:`, workbooksData?.map(w => w.source_file));
      }
    };
    
    const handleKPIGraphNav = (e: Event) => {
      const customEvent = e as CustomEvent;
      setRequestedDashboardsForGraph(customEvent.detail.dashboards);
      setCurrentView('kpiGraph');
    };
    window.addEventListener('NAVIGATE_DASHBOARD', handleNav);
    window.addEventListener('NAVIGATE_KPI_GRAPH', handleKPIGraphNav);
    return () => {
      window.removeEventListener('NAVIGATE_DASHBOARD', handleNav);
      window.removeEventListener('NAVIGATE_KPI_GRAPH', handleKPIGraphNav);
    };
  }, [workbooksData]);
  const handleUploadSuccess = (dataArray: any[]) => {
    // Accumulate across uploads — don't replace, append new files
    setWorkbooksData(prev => {
      const existing = prev || [];
      // Avoid exact duplicates by source_file name
      const newFiles = dataArray.filter(
        newWb => !existing.some(e => e.source_file === newWb.source_file)
      );
      return [...existing, ...newFiles];
    });
    setSelectedWorkbook(null);
    setSelectedDashboard(null);
    setRecommendationsData(null);
    setCurrentView('areas');
  };
  const goToHub = () => {
    setSelectedWorkbook(null);
    setSelectedDashboard(null);
    setSelectedAreaId(null);
    setCurrentView('areas');
  };
  const goToAreas = () => {
    setSelectedAreaId(null);
    setCurrentView('areas');
  };
  const goToInventory = (workbook: any) => {
    setInventoryBackView(currentView);
    setSelectedWorkbook(workbook);
    setSelectedDashboard(null);
    setCurrentView('inventory');
  };
  const goBackFromInventory = () => {
    setCurrentView(inventoryBackView);
  };
  const goBackToInventory = () => {
    setSelectedDashboard(null);
    if (inventoryBackView === 'overview') {
      setCurrentView('overview');
    } else {
      setCurrentView('inventory');
    }
  };
  const goToDetail = (dashboard: any) => {
    setSelectedDashboard(dashboard);
    setCurrentView('detail');
  };
  return (
    <Layout activeView={currentView} onNavigate={(view) => setCurrentView(view as View)}>
      <div className="w-full">
        {/* ── Governance Hub Removed ───────────────────────────── */}
        {/* ── BI Landscape Graph ─────────────────────────────── */}
        {currentView === 'landscape' && (
          <LandscapeView
            workbooksData={workbooksData || []}
            selectedLOBs={selectedLOBs}
            setSelectedLOBs={setSelectedLOBs}
            selectedUserGroups={selectedUserGroups}
            setSelectedUserGroups={setSelectedUserGroups}
          />
        )}
        {/* ── BI Assist ────────────────────────────────────── */}
        {currentView === 'bi_assist' && (
          <BIAssistView />
        )}
        {/* ── Recommendations ───────────────────────────────── */}
        {currentView === 'recommendations' && (
          <RecommendationsView
            cachedData={recommendationsData}
            onCacheData={(data) => setRecommendationsData(data)}
          />
        )}
        {/* ── Upload / Scanner ─────────────────────────── */}
        {currentView === 'upload' && (
          <div className="animate-in fade-in zoom-in-95 duration-200 max-w-3xl mx-auto">
            <div className="flex justify-between items-center mb-8">
              <div>
                <h2 className="text-2xl font-bold tracking-tight">Repository Scanner</h2>
                <p className="text-sm text-muted-foreground mt-1">
                  Drop a folder or individual Tableau workbook files to begin analysis
                </p>
              </div>
              <button
                onClick={goToHub}
                className="text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
            <UploadArea onUploadSuccess={handleUploadSuccess} />
          </div>
        )}
        {/* ── Business Areas ───────────────────────────── */}
        {currentView === 'areas' && (
          <BusinessAreasView
            workbooksData={workbooksData || []}
            selectedLOBs={selectedLOBs}
            setSelectedLOBs={setSelectedLOBs}
            selectedUserGroups={selectedUserGroups}
            setSelectedUserGroups={setSelectedUserGroups}
            onSelectArea={(areaId) => {
              setSelectedAreaId(areaId);
              setCurrentView('areaDetail');
            }}
          />
        )}
        {/* ── Area Detail ──────────────────────────────── */}
        {currentView === 'areaDetail' && selectedAreaId && (
          <AreaDetailView
            areaId={selectedAreaId}
            workbooksData={workbooksData || []}
            selectedLOBs={selectedLOBs}
            setSelectedLOBs={setSelectedLOBs}
            selectedUserGroups={selectedUserGroups}
            setSelectedUserGroups={setSelectedUserGroups}
            onBack={goToAreas}
            onSelectFile={goToInventory}
            onSelectDashboard={(wb, db) => {
              setSelectedWorkbook(wb);
              setSelectedDashboard(db);
              setInventoryBackView('areaDetail');
              setCurrentView('detail');
            }}
          />
        )}
        {/* 🟡 Level 2: Dashboard Overview (Global Dashboard List) */}
        {currentView === 'overview' && (
          <DashboardOverviewView
            workbooksData={workbooksData || []}
            onSelectDashboard={(wb, db) => {
              setSelectedWorkbook(wb);
              setSelectedDashboard(db);
              setInventoryBackView('overview');
              setCurrentView('detail');
            }}
          />
        )}
        {/* ── Level 2: Inventory (Dashboards) ──────────── */}
        {currentView === 'inventory' && selectedWorkbook && (
          <div className="animate-in fade-in slide-in-from-right-4 duration-300">
            <div className="flex items-center gap-3 mb-6">
              <button onClick={goBackFromInventory} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                {inventoryBackView === 'areas' ? 'Back to Areas' : 
                 inventoryBackView === 'areaDetail' ? 'Back to Area Detail' : 
                 inventoryBackView === 'landscape' ? 'Back to Landscape' : 
                 inventoryBackView === 'overview' ? 'Back to Overview' : 'Back to Areas'}
              </button>
              <span className="text-muted-foreground/40 text-xs">/</span>
              <span className="text-xs font-medium text-foreground truncate max-w-xs">{selectedWorkbook.source_file}</span>
            </div>
            <InventoryView
              data={selectedWorkbook}
              onViewDetails={goToDetail}
            />
          </div>
        )}
        {/* ── Level 3: Detail View ─────────────────────── */}
        {currentView === 'detail' && selectedDashboard && selectedWorkbook && (
          <div className="animate-in fade-in slide-in-from-right-4 duration-300">
            <div className="flex items-center gap-3 mb-6">
              <button onClick={goBackFromInventory} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                {inventoryBackView === 'areas' ? 'Back to Areas' : 
                 inventoryBackView === 'areaDetail' ? 'Back to Area Detail' : 
                 inventoryBackView === 'landscape' ? 'Back to Landscape' : 
                 inventoryBackView === 'overview' ? 'Back to Overview' : 'Back to Areas'}
              </button>
              <span className="text-muted-foreground/40 text-xs">/</span>
              <button onClick={goBackToInventory} className="text-xs text-muted-foreground hover:text-foreground transition-colors truncate max-w-[150px]">{selectedWorkbook.source_file}</button>
              <span className="text-muted-foreground/40 text-xs">/</span>
              <span className="text-xs font-medium text-foreground truncate max-w-xs">{selectedDashboard.name}</span>
            </div>
            <DetailView
              dashboard={selectedDashboard}
              workbookData={selectedWorkbook}
              onBack={goBackToInventory}
              onResolveKpis={(reportId) => {
                setOntologyFilterReportId(String(reportId));
                setCurrentView('ontology');
              }}
            />
          </div>
        )}
        {/* ── Ontology Bank ───────────────────────────────── */}
        {currentView === 'ontology' && (
          <div className="animate-in fade-in slide-in-from-right-4 duration-300">
            <OntologyBankView filterReportId={ontologyFilterReportId} />
          </div>
        )}
        {/* ── KPI Graph View ────────────────────────────── */}
        {currentView === 'kpiGraph' && (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-300">
            <div className="flex items-center gap-3 mb-6">
              <button onClick={() => setCurrentView('areas')} className="text-xs text-muted-foreground hover:text-foreground transition-colors">
                Back to Business Areas
              </button>
              <span className="text-muted-foreground/40 text-xs">/</span>
              <span className="text-xs font-medium text-foreground truncate max-w-xs">KPI Lineage Graph</span>
            </div>
            <KPIDashboardGraph dashboards={requestedDashboardsForGraph} />
          </div>
        )}
      </div>
    </Layout>
  );
}
export default App;
