import { API_BASE_URL } from '@/config';
import React, { useState, useRef, useEffect } from 'react';
import { MessageCircle, Send, X, Bot, User, Database, Package, Brain, Minimize2, Maximize2, LayoutDashboard } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  source?: 'metadata' | 'data' | 'llm';
  timestamp: Date;
}

const SOURCE_ICON: Record<string, React.ReactNode> = {
  metadata: <Database className="w-3 h-3 text-amber-400" />,
  data:     <Package className="w-3 h-3 text-violet-400" />,
  llm:      <Brain className="w-3 h-3 text-sky-400" />,
};

// Markdown Link Parser
function parseMessageText(text: string) {
  const parts = text.split(/(\[.*?\]\(nav:\/\/.*?\))/g);
  return parts.map((part, i) => {
    const match = part.match(/\[(.*?)\]\(nav:\/\/(.*?)\)/);
    if (match) {
      const [_, name, file] = match;
      if (file.startsWith('kpi_graph|')) {
        const dashboardList = decodeURIComponent(file.substring('kpi_graph|'.length));
        return (
          <button
            key={i}
            onClick={(e) => {
              e.preventDefault();
              console.log(`Clicked KPI graph link for: ${dashboardList}`);
              window.dispatchEvent(new CustomEvent('NAVIGATE_KPI_GRAPH', { detail: { dashboards: dashboardList } }));
            }}
            className="inline-flex items-center gap-1 text-emerald-400 hover:text-emerald-300 underline underline-offset-2 font-medium mx-1 mt-2 p-1.5 border border-emerald-500/30 rounded-md bg-emerald-500/10"
            title={`View KPI graph for ${dashboardList}`}
          >
            <Database className="w-3.5 h-3.5" />
            {name}
          </button>
        );
      }

      return (
        <button
          key={i}
          onClick={(e) => {
            e.preventDefault();
            console.log(`Clicked dashboard link: name=${name}, file=${file}`);
            window.dispatchEvent(new CustomEvent('NAVIGATE_DASHBOARD', { detail: { workbook: file, dashboard: name } }));
          }}
          className="inline-flex items-center gap-1 text-indigo-400 hover:text-indigo-300 underline underline-offset-2 font-medium mx-1"
          title={`Open dashboard in ${file}`}
        >
          <LayoutDashboard className="w-3 h-3" />
          {name}
        </button>
      );
    }
    return <span key={i} className="whitespace-pre-wrap">{part}</span>;
  });
}
const SOURCE_LABEL: Record<string, string> = {
  metadata: 'SQLite Metadata',
  data:     'Extract Data',
  llm:      'AI Knowledge',
};

const DEFAULT_SUGGESTIONS = [
  'How many dashboards are in this workbook?',
  'What tables does this workbook use?',
  'What calculated fields are defined?',
  'Summarize what this workbook is about',
];

const GLOBAL_SUGGESTIONS = [
  'Do we have any dashboards that has Claims Distribution by Region?',
  'Is any dashboard talking about aging of the cases?',
  'Do we have any dashboard where we see cases broken down by NiIGO?',
  'Do we have any dashboards where we have a chart for car models?',
];

export function ChatPanel({ workbookName }: { workbookName: string }) {
  const [isOpen, setIsOpen] = useState(false);
  const [isMinimized, setIsMinimized] = useState(false);
  const isGlobal = workbookName === 'Global Portfolio';
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      text: isGlobal 
        ? `Hi! I'm your Conversational BI assistant. Ask me anything about your **Global Portfolio** of dashboards, their charts, and the data they use.`
        : `Hi! I'm your Conversational BI assistant. Ask me anything about **${workbookName || 'this workbook'}** — its dashboards, tables, calculated fields, or data.`,
      source: undefined,
      timestamp: new Date(),
    }
  ]);
  const [input, setInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  useEffect(() => {
    if (isOpen && !isMinimized) {
      setTimeout(() => inputRef.current?.focus(), 100);
    }
  }, [isOpen, isMinimized]);

  const sendMessage = async (text: string) => {
    if (!text.trim() || isLoading) return;
    const userMsg: Message = { role: 'user', text: text.trim(), timestamp: new Date() };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setIsLoading(true);

    try {
      const res = await fetch(`${API_BASE_URL}/api/v1/chat/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text.trim(), workbook_name: workbookName }),
      });
      const data = await res.json();
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: data.answer || 'Sorry, I could not find an answer.',
        source: data.source,
        timestamp: new Date(),
      }]);
    } catch {
      setMessages(prev => [...prev, {
        role: 'assistant',
        text: 'Could not reach the backend. Please make sure the FastAPI server is running.',
        source: 'llm',
        timestamp: new Date(),
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKey = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(input); }
  };

  if (!isOpen) {
    return (
      <button
        onClick={() => setIsOpen(true)}
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 px-4 py-3 bg-primary text-primary-foreground rounded-2xl shadow-2xl shadow-primary/30 hover:bg-primary/90 transition-all hover:scale-105 font-semibold text-sm group"
      >
        <MessageCircle className="w-5 h-5" />
        <span>Ask about this workbook</span>
        <div className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
      </button>
    );
  }

  return (
    <div className={`fixed bottom-6 right-6 z-50 flex flex-col rounded-2xl border border-border shadow-2xl shadow-black/40 bg-background transition-all duration-300 ${isMinimized ? 'h-14 w-72' : 'h-[520px] w-[380px]'}`}>
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border rounded-t-2xl bg-card flex-shrink-0">
        <div className="w-8 h-8 rounded-xl bg-primary/15 flex items-center justify-center">
          <Bot className="w-4 h-4 text-primary" />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-bold text-foreground">Conversational BI</p>
          <p className="text-[10px] text-muted-foreground truncate">{workbookName || 'No workbook loaded'}</p>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => setIsMinimized(!isMinimized)} className="p-1.5 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors">
            {isMinimized ? <Maximize2 className="w-3.5 h-3.5" /> : <Minimize2 className="w-3.5 h-3.5" />}
          </button>
          <button onClick={() => setIsOpen(false)} className="p-1.5 hover:bg-accent rounded-lg text-muted-foreground hover:text-foreground transition-colors">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {!isMinimized && (
        <>
          {/* Messages */}
          <div className="flex-1 overflow-y-auto p-3 space-y-3">
            {messages.map((msg, i) => (
              <div key={i} className={`flex gap-2 ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
                {/* Avatar */}
                <div className={`w-6 h-6 rounded-full flex items-center justify-center flex-shrink-0 mt-0.5 ${msg.role === 'user' ? 'bg-primary/20' : 'bg-muted'}`}>
                  {msg.role === 'user' ? <User className="w-3 h-3 text-primary" /> : <Bot className="w-3 h-3 text-muted-foreground" />}
                </div>
                {/* Bubble */}
                <div className={`max-w-[85%] ${msg.role === 'user' ? 'items-end' : 'items-start'} flex flex-col gap-1`}>
                  <div className={`px-3 py-2 rounded-2xl text-xs leading-relaxed ${
                    msg.role === 'user'
                      ? 'bg-primary text-primary-foreground rounded-tr-sm'
                      : 'bg-muted text-foreground rounded-tl-sm'
                  }`}>
                    {parseMessageText(msg.text)}
                  </div>
                  {msg.source && (
                    <div className="flex items-center gap-1 px-1">
                      {SOURCE_ICON[msg.source]}
                      <span className="text-[9px] text-muted-foreground">{SOURCE_LABEL[msg.source]}</span>
                    </div>
                  )}
                </div>
              </div>
            ))}

            {isLoading && (
              <div className="flex gap-2">
                <div className="w-6 h-6 rounded-full bg-muted flex items-center justify-center flex-shrink-0 mt-0.5">
                  <Bot className="w-3 h-3 text-muted-foreground" />
                </div>
                <div className="bg-muted px-3 py-2.5 rounded-2xl rounded-tl-sm flex items-center gap-1.5">
                  {[0, 1, 2].map(i => (
                    <div key={i} className="w-1.5 h-1.5 rounded-full bg-muted-foreground/50 animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
                  ))}
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Suggestions */}
          <div className="px-3 pb-2">
            <p className="text-[10px] text-muted-foreground mb-1.5 font-medium">Try asking:</p>
            <div className="flex flex-col gap-1.5 pb-2">
              {(isGlobal ? GLOBAL_SUGGESTIONS : DEFAULT_SUGGESTIONS).map((s, i) => (
                <button
                  key={i}
                  onClick={() => sendMessage(s)}
                  className="px-2.5 py-1.5 bg-muted hover:bg-accent text-xs text-muted-foreground hover:text-foreground rounded-lg border border-border transition-colors text-left"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>

          {/* Input */}
          <div className="p-3 border-t border-border flex-shrink-0">
            <div className="flex gap-2 items-center bg-muted/50 rounded-xl border border-border px-3 py-2">
              <input
                ref={inputRef}
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={handleKey}
                placeholder="Ask about dashboards, tables, fields..."
                className="flex-1 bg-transparent text-xs text-foreground placeholder:text-muted-foreground outline-none"
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={!input.trim() || isLoading}
                className="w-6 h-6 rounded-lg bg-primary flex items-center justify-center disabled:opacity-30 transition-opacity hover:bg-primary/90"
              >
                <Send className="w-3 h-3 text-primary-foreground" />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}