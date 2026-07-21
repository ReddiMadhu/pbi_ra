import React from 'react';
import { Shield, LayoutDashboard, Database, Activity, Settings, ChevronRight, Briefcase, Network, MessageCircle, Sparkles, BookOpen, Layers } from 'lucide-react';
import { API_BASE_URL } from '@/config';

const navItems = [
  { icon: Briefcase, label: 'BI Explore', id: 'areas' },
  { icon: Layers, label: 'Scope Approval', id: 'scope_approval' },
  { icon: Database, label: 'Dashboard Overview', id: 'overview' },
  { icon: BookOpen, label: 'KPI Ontology Mapping', id: 'kpi_governance' },
  { icon: Network, label: 'BI Landscape Graph', id: 'landscape' },
  { icon: Sparkles, label: 'Recommendations', id: 'recommendations' },
  { icon: MessageCircle, label: 'BI Assist', id: 'bi_assist' },
];


export function Layout({ children, activeView, onNavigate }: { children: React.ReactNode; activeView?: string; onNavigate?: (view: string) => void }) {
  const [pendingScopeCount, setPendingScopeCount] = React.useState(0);

  React.useEffect(() => {
    const fetchPendingCount = async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/api/v1/ontology/dashboards/pending-scope`);
        const data = await res.json();
        if (Array.isArray(data)) {
          setPendingScopeCount(data.length);
        }
      } catch (e) {
        // ignore
      }
    };
    fetchPendingCount();
    const interval = setInterval(fetchPendingCount, 15000); // refresh every 15s
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen bg-background text-foreground font-sans overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 flex flex-col border-r border-border bg-sidebar shrink-0">
        {/* Logo */}
        <div className="h-16 flex items-center px-5 border-b border-border gap-3">
          <div className="w-8 h-8 bg-primary rounded-lg flex items-center justify-center shadow-lg shadow-primary/20">
            <Shield className="w-4 h-4 text-primary-foreground" />
          </div>
          <div>
            <h1 className="text-sm font-bold tracking-tight leading-none">BI Compass</h1>
            <p className="text-[10px] text-muted-foreground mt-0.5 tracking-widest uppercase">Enterprise</p>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-3 py-4 space-y-0.5">
          <p className="px-3 text-[10px] font-semibold tracking-widest uppercase text-muted-foreground mb-2">Platform</p>
          {navItems.map(({ icon: Icon, label, id }) => {
            const isActive = activeView === id;
            return (
              <div
                key={id}
                onClick={() => onNavigate && onNavigate(id)}
                className={`flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium cursor-pointer transition-all group ${
                  isActive
                    ? 'bg-primary/15 text-primary'
                    : 'text-sidebar-foreground hover:bg-accent hover:text-accent-foreground'
                }`}
              >
                <div className="flex items-center gap-3">
                  <Icon className={`w-4 h-4 ${isActive ? 'text-primary' : 'text-muted-foreground group-hover:text-accent-foreground'}`} />
                  {label}
                </div>
                {id === 'scope_approval' && pendingScopeCount > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-indigo-500 text-indigo-50 text-[10px] font-bold">
                    {pendingScopeCount}
                  </span>
                )}
                {isActive && id !== 'scope_approval' && <ChevronRight className="w-3 h-3 text-primary opacity-60" />}
              </div>
            );
          })}
        </nav>

        {/* Bottom */}
        <div className="p-3 border-t border-border space-y-0.5">
          <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-sidebar-foreground hover:bg-accent cursor-pointer transition-all">
            <Settings className="w-4 h-4 text-muted-foreground" />
            Configuration
          </div>
          {/* Status bar */}
          <div className="mt-2 px-3 py-2 rounded-lg bg-muted/50 border border-border">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
              <span className="text-xs text-muted-foreground">SQLite · Local Mode</span>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5 truncate">No external DB required</p>
          </div>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Topbar */}
        <header className="h-16 flex items-center justify-between px-8 border-b border-border bg-background/80 backdrop-blur shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-foreground">BI Compass</h2>
            <p className="text-xs text-muted-foreground">Insurance Analytics · Tableau Repository Management</p>
          </div>
          <div className="flex items-center gap-4">
            <button
              onClick={() => onNavigate && onNavigate('kpi_ontology')}
              className="flex items-center gap-2 text-xs font-semibold text-indigo-400 border border-indigo-500/25 bg-indigo-500/5 hover:bg-indigo-500/10 rounded-full px-3 py-1.5 transition-all"
            >
              <BookOpen className="w-3.5 h-3.5 text-indigo-400" />
              KPI Ontology Bank
            </button>
            <div className="w-8 h-8 rounded-full bg-primary/20 border border-primary/30 flex items-center justify-center text-primary text-xs font-bold">
              G
            </div>
          </div>
        </header>

        {/* Content */}
        <div className="flex-1 overflow-auto p-8">
          {children}
        </div>
      </main>
    </div>
  );
}
