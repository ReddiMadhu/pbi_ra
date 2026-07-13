import { API_BASE_URL } from '@/config';
import React, { useState, useRef, useEffect } from 'react';
import { MessageCircle, Send, Bot, User, Database, Package, Brain, LayoutDashboard } from 'lucide-react';

interface Message {
  role: 'user' | 'assistant';
  text: string;
  source?: 'metadata' | 'data' | 'llm';
  timestamp: Date;
}

const SOURCE_ICON: Record<string, React.ReactNode> = {
  metadata: <Database className="w-4 h-4 text-amber-400" />,
  data:     <Package className="w-4 h-4 text-violet-400" />,
  llm:      <Brain className="w-4 h-4 text-sky-400" />,
};

const SOURCE_LABEL: Record<string, string> = {
  metadata: 'SQLite Metadata',
  data:     'Extract Data',
  llm:      'AI Knowledge',
};

const GLOBAL_SUGGESTIONS = [
  'Do we have any dashboards that has Claims Distribution by Region?',
  'Is any dashboard talking about aging of the cases?',
  'Do we have any dashboard where we see cases broken down by NiIGO?',
  'Do we have any dashboards where we have a chart for car models?',
];

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
              window.dispatchEvent(new CustomEvent('NAVIGATE_KPI_GRAPH', { detail: { dashboards: dashboardList } }));
            }}
            className="inline-flex items-center gap-1.5 text-emerald-400 hover:text-emerald-300 underline underline-offset-2 font-medium mx-1 mt-2 p-2 border border-emerald-500/30 rounded-md bg-emerald-500/10"
            title={`View KPI graph for ${dashboardList}`}
          >
            <Database className="w-4 h-4" />
            {name}
          </button>
        );
      }

      return (
        <button
          key={i}
          onClick={(e) => {
            e.preventDefault();
            window.dispatchEvent(new CustomEvent('NAVIGATE_DASHBOARD', { detail: { workbook: file, dashboard: name } }));
          }}
          className="inline-flex items-center gap-1.5 text-indigo-400 hover:text-indigo-300 underline underline-offset-2 font-medium mx-1"
          title={`Open dashboard in ${file}`}
        >
          <LayoutDashboard className="w-4 h-4" />
          {name}
        </button>
      );
    }
    return <span key={i} className="whitespace-pre-wrap">{part}</span>;
  });
}

export function BIAssistView() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: 'assistant',
      text: `Hi! I'm your Conversational BI assistant. Ask me anything about your **Global Portfolio** of dashboards, their charts, and the data they use. I can analyze all your uploaded metadata to answer your questions.`,
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
    inputRef.current?.focus();
  }, []);

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
        body: JSON.stringify({ question: text.trim(), workbook_name: 'Global Portfolio' }),
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

  return (
    <div className="flex flex-col h-[calc(100vh-8rem)] max-w-4xl mx-auto animate-in fade-in zoom-in-95 duration-300">
      {/* Header */}
      <div className="flex items-center gap-4 px-6 py-5 border-b border-border bg-card rounded-t-2xl shrink-0">
        <div className="w-12 h-12 rounded-2xl bg-primary/15 flex items-center justify-center">
          <MessageCircle className="w-6 h-6 text-primary" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-foreground">BI Assist</h2>
          <p className="text-sm text-muted-foreground mt-0.5">Global Portfolio Chat</p>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-6 space-y-6 bg-muted/10">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-4 max-w-[85%] ${msg.role === 'user' ? 'ml-auto flex-row-reverse' : 'mr-auto flex-row'}`}>
            <div className={`w-10 h-10 rounded-full flex items-center justify-center shrink-0 ${msg.role === 'user' ? 'bg-primary/20' : 'bg-secondary'}`}>
              {msg.role === 'user' ? <User className="w-5 h-5 text-primary" /> : <Bot className="w-5 h-5 text-secondary-foreground" />}
            </div>
            
            <div className={`flex flex-col gap-2 min-w-0 ${msg.role === 'user' ? 'items-end' : 'items-start'}`}>
              <div className={`px-5 py-4 rounded-3xl text-sm leading-relaxed ${
                msg.role === 'user'
                  ? 'bg-primary text-primary-foreground rounded-tr-sm'
                  : 'bg-card text-foreground rounded-tl-sm border border-border shadow-sm'
              }`}>
                {parseMessageText(msg.text)}
              </div>
              
              {msg.source && (
                <div className="flex items-center gap-1.5 px-2 opacity-70">
                  {SOURCE_ICON[msg.source]}
                  <span className="text-xs text-muted-foreground font-medium">{SOURCE_LABEL[msg.source]}</span>
                </div>
              )}
            </div>
          </div>
        ))}

        {isLoading && (
          <div className="flex gap-4 max-w-[85%] mr-auto">
            <div className="w-10 h-10 rounded-full bg-secondary flex items-center justify-center shrink-0">
              <Bot className="w-5 h-5 text-secondary-foreground" />
            </div>
            <div className="bg-card px-5 py-4 rounded-3xl rounded-tl-sm border border-border shadow-sm flex items-center gap-2">
              {[0, 1, 2].map(i => (
                <div key={i} className="w-2.5 h-2.5 rounded-full bg-primary/60 animate-bounce" style={{ animationDelay: `${i * 0.15}s` }} />
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      <div className="px-6 py-4 bg-muted/10 border-t border-border shrink-0">
        <p className="text-xs text-muted-foreground mb-3 font-semibold uppercase tracking-wider">Suggested Questions</p>
        <div className="flex flex-wrap gap-2">
          {GLOBAL_SUGGESTIONS.map((s, i) => (
            <button
              key={i}
              onClick={() => sendMessage(s)}
              className="px-4 py-2 bg-card hover:bg-accent text-sm text-foreground rounded-xl border border-border transition-colors text-left font-medium shadow-sm hover:shadow"
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="p-6 bg-card border-t border-border rounded-b-2xl shrink-0">
        <div className="flex gap-3 items-center bg-muted/50 rounded-2xl border border-border px-4 py-3 focus-within:ring-2 focus-within:ring-primary/50 focus-within:border-primary transition-all shadow-inner">
          <input
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKey}
            placeholder="Ask about dashboards, tables, fields..."
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
          />
          <button
            onClick={() => sendMessage(input)}
            disabled={!input.trim() || isLoading}
            className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center disabled:opacity-30 transition-all hover:bg-primary/90 hover:scale-105 active:scale-95 shadow-md"
          >
            <Send className="w-4 h-4 text-primary-foreground" />
          </button>
        </div>
      </div>
    </div>
  );
}