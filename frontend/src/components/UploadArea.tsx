import { API_BASE_URL } from '@/config';
import React from 'react';
import { UploadCloud, File as FileIcon, AlertCircle, Loader2, FolderOpen, CheckCircle2, Link as LinkIcon, Globe } from 'lucide-react';

export function UploadArea({ onUploadSuccess }: { onUploadSuccess: (data: any) => void }) {
  const [activeTab, setActiveTab] = React.useState<'folder' | 'link'>('folder');
  const [workspaceLink, setWorkspaceLink] = React.useState('');
  const [isDragging, setIsDragging] = React.useState(false);
  const [isUploading, setIsUploading] = React.useState(false);
  const [uploadProgress, setUploadProgress] = React.useState<{ current: number; total: number } | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const fileInputRef = React.useRef<HTMLInputElement>(null);

  const handleDrag = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setIsDragging(true);
    } else if (e.type === 'dragleave') {
      setIsDragging(false);
    }
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
    if (e.dataTransfer.items) {
      const files: File[] = [];
      const items = Array.from(e.dataTransfer.items);
      const promises = items.map(item => {
        if (item.kind === 'file') {
          const entry = item.webkitGetAsEntry();
          if (entry) return traverseFileTree(entry, files);
        }
        return Promise.resolve();
      });
      await Promise.all(promises);
      await processFiles(files);
    }
  };

  const traverseFileTree = (item: any, fileList: File[]): Promise<void> => {
    return new Promise((resolve) => {
      if (item.isFile) {
        item.file((file: File) => {
          if (file.name.endsWith('.twb') || file.name.endsWith('.twbx')) {
            fileList.push(file);
          }
          resolve();
        });
      } else if (item.isDirectory) {
        const dirReader = item.createReader();
        const entries: Promise<void>[] = [];
        const readEntries = () => {
          dirReader.readEntries((results: any[]) => {
            if (results.length) {
              for (const entry of results) {
                entries.push(traverseFileTree(entry, fileList));
              }
              readEntries();
            } else {
              Promise.all(entries).then(() => resolve());
            }
          });
        };
        readEntries();
      } else {
        resolve();
      }
    });
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      const files = Array.from(e.target.files).filter(
        f => f.name.endsWith('.twb') || f.name.endsWith('.twbx')
      );
      await processFiles(files);
    }
  };

  const processFiles = async (files: File[]) => {
    if (files.length === 0) {
      setError('No valid .twb or .twbx files found in the selected folder.');
      return;
    }
    setError(null);
    setIsUploading(true);
    setUploadProgress({ current: 0, total: files.length });
    const allData: any[] = [];

    try {
      await fetch(`${API_BASE_URL}/api/v1/upload/clear`, { method: 'POST' });
    } catch (e) {
      console.warn("Failed to clear previous session data", e);
    }

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      const formData = new FormData();
      formData.append('file', file);
      try {
        const response = await fetch(`${API_BASE_URL}/api/v1/upload/parse`, {
          method: 'POST',
          body: formData,
        });
        if (!response.ok) {
          console.error(`Failed to parse file: ${file.name}`);
          continue;
        }
        allData.push(await response.json());
      } catch (err: any) {
        console.error(`Error uploading ${file.name}:`, err);
      }
      setUploadProgress({ current: i + 1, total: files.length });
    }

    setIsUploading(false);
    setUploadProgress(null);

    if (allData.length > 0) {
      onUploadSuccess(allData);
    } else {
      setError('Failed to process any files. Make sure the FastAPI backend is running on port 8000.');
    }
  };

  const handleLinkSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!workspaceLink) return;
    setError(null);
    setIsUploading(true);
    
    // Mock the upload success for a link
    setTimeout(() => {
      setIsUploading(false);
      onUploadSuccess([{ source_file: `workspace_${Date.now()}.twbx`, dashboards: [], datasources: [] }]);
    }, 1500);
  };

  const progressPercent = uploadProgress ? Math.round((uploadProgress.current / uploadProgress.total) * 100) : 0;

  return (
    <div className="w-full max-w-3xl mx-auto flex flex-col gap-6">
      {/* Tabs */}
      <div className="flex bg-muted/50 p-1 rounded-xl w-fit mx-auto">
        <button
          onClick={() => setActiveTab('folder')}
          className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'folder' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
          }`}
        >
          <FolderOpen className="w-4 h-4" />
          Upload Folder
        </button>
        <button
          onClick={() => setActiveTab('link')}
          className={`flex items-center gap-2 px-6 py-2.5 rounded-lg text-sm font-medium transition-all ${
            activeTab === 'link' ? 'bg-background shadow-sm text-foreground' : 'text-muted-foreground hover:text-foreground hover:bg-background/50'
          }`}
        >
          <LinkIcon className="w-4 h-4" />
          Workspace Link
        </button>
      </div>

      {activeTab === 'folder' ? (
        <div
          className={`relative flex flex-col items-center justify-center w-full h-72 rounded-2xl border-2 border-dashed transition-all duration-300 cursor-pointer ${
            isDragging
              ? 'border-primary bg-primary/10 scale-[1.01]'
              : 'border-border bg-card hover:bg-accent/30 hover:border-primary/50'
          }`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
          onClick={() => !isUploading && fileInputRef.current?.click()}
        >
          <input
            type="file"
            ref={fileInputRef}
            onChange={handleFileChange}
            accept=".twb,.twbx"
            multiple
            // @ts-ignore
            webkitdirectory="true"
            directory="true"
            className="hidden"
          />

          {isUploading ? (
            <div className="flex flex-col items-center space-y-5 px-8 w-full">
              <Loader2 className="w-12 h-12 text-primary animate-spin" />
              <div className="text-center">
                <p className="text-base font-semibold text-foreground">Processing Tableau Repository...</p>
                <p className="text-sm text-muted-foreground mt-1">
                  {uploadProgress?.current} of {uploadProgress?.total} files analyzed
                </p>
              </div>
              {/* Progress Bar */}
              <div className="w-full max-w-sm">
                <div className="flex justify-between text-xs text-muted-foreground mb-1.5">
                  <span>Extracting Metadata</span>
                  <span>{progressPercent}%</span>
                </div>
                <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                  <div
                    className="h-full bg-primary rounded-full transition-all duration-500"
                    style={{ width: `${progressPercent}%` }}
                  />
                </div>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center space-y-4 text-center px-8">
              <div className={`w-16 h-16 rounded-2xl flex items-center justify-center transition-colors ${isDragging ? 'bg-primary/20' : 'bg-muted'}`}>
                <FolderOpen className={`w-8 h-8 transition-colors ${isDragging ? 'text-primary' : 'text-muted-foreground'}`} />
              </div>
              <div>
                <h3 className="text-lg font-semibold text-foreground">Drop your Tableau Repository</h3>
                <p className="text-sm text-muted-foreground mt-1 max-w-sm">
                  Drag and drop a folder or individual <code className="text-primary text-xs bg-primary/10 px-1.5 py-0.5 rounded">.twb</code> / <code className="text-primary text-xs bg-primary/10 px-1.5 py-0.5 rounded">.twbx</code> files here
                </p>
              </div>
              <div className="flex items-center gap-4 text-xs text-muted-foreground">
                <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> Recursive folder scan</span>
                <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> Batch processing</span>
                <span className="flex items-center gap-1.5"><CheckCircle2 className="w-3.5 h-3.5 text-emerald-500" /> AI Classification</span>
              </div>
            </div>
          )}
        </div>
      ) : (
        <div className="w-full h-72 rounded-2xl border-2 border-border bg-card flex flex-col items-center justify-center p-8">
          {isUploading ? (
            <div className="flex flex-col items-center space-y-5 px-8 w-full">
              <Loader2 className="w-12 h-12 text-primary animate-spin" />
              <div className="text-center">
                <p className="text-base font-semibold text-foreground">Connecting to Workspace...</p>
                <p className="text-sm text-muted-foreground mt-1">Retrieving dashboards</p>
              </div>
            </div>
          ) : (
            <div className="w-full max-w-md flex flex-col items-center text-center">
              <div className="w-16 h-16 rounded-2xl bg-indigo-500/10 flex items-center justify-center mb-6">
                <Globe className="w-8 h-8 text-indigo-500" />
              </div>
              <h3 className="text-lg font-semibold text-foreground mb-2">Connect Tableau Workspace</h3>
              <p className="text-sm text-muted-foreground mb-8">
                Paste the URL of your Tableau workspace to automatically sync all dashboards.
              </p>
              <form onSubmit={handleLinkSubmit} className="w-full flex gap-3">
                <input
                  type="url"
                  placeholder="https://prod-useast-a.online.tableau.com/..."
                  value={workspaceLink}
                  onChange={(e) => setWorkspaceLink(e.target.value)}
                  className="flex-1 px-4 py-2.5 rounded-lg border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-primary/50"
                  required
                />
                <button
                  type="submit"
                  disabled={!workspaceLink}
                  className="px-6 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-medium hover:bg-primary/90 disabled:opacity-50 transition-colors"
                >
                  Connect
                </button>
              </form>
            </div>
          )}
        </div>
      )}

      {error && (
        <div className="mt-4 p-4 rounded-xl bg-destructive/10 border border-destructive/30 flex items-start gap-3 text-destructive">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <p className="text-sm font-medium">{error}</p>
        </div>
      )}
    </div>
  );
}