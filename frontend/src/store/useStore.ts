import { create } from 'zustand';

interface ScanHistory {
  id: number;
  directory_path: string;
  status: string;
  total_files: number;
  processed_files: number;
  started_at: string;
  completed_at: string | null;
}

interface GovernanceStore {
  activeScanId: number | null;
  setActiveScanId: (id: number | null) => void;
  recentScans: ScanHistory[];
  setRecentScans: (scans: ScanHistory[]) => void;
  selectedDomain: string | null;
  setSelectedDomain: (domain: string | null) => void;
}

export const useStore = create<GovernanceStore>((set) => ({
  activeScanId: null,
  setActiveScanId: (id) => set({ activeScanId: id }),
  recentScans: [],
  setRecentScans: (scans) => set({ recentScans: scans }),
  selectedDomain: null,
  setSelectedDomain: (domain) => set({ selectedDomain: domain }),
}));
