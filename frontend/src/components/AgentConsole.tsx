import { API_BASE_URL } from '@/config';
import React, { useState, useRef } from 'react';
import { CheckCircle2, Loader2, Brain, Shield, AlertTriangle, Lightbulb, Play, ChevronDown, ChevronUp, Circle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from './ui/card';

interface AgentStep {
  step: string;
  status: 'idle' | 'running' | 'done';
  output: string | null;
}

interface AgentResult {
  classification: { domain: string; complexity: number; summary: string; is_real_ai?: boolean } | null;
  risks: { risk_type: string; description: string; severity: string }[];
  recommendations: string[];
}

const PIPELINE_STEPS = [
  { key: 'Planning Analysis',       icon: Brain,         color: 'text-sky-400',    bg: 'bg-sky-500/15 border-sky-500/30',    label: 'Agent 1 · Planner' },
  { key: 'Domain Classification',   icon: Shield,        color: 'text-violet-400', bg: 'bg-violet-500/15 border-violet-500/30', label: 'Agent 2 · Classifier' },
  { key: 'Risk Assessment',         icon: AlertTriangle, color: 'text-rose-400',   bg: 'bg-rose-500/15 border-rose-500/30',  label: 'Agent 3 · Risk Assessor' },
  { key: 'Generating Recommendations', icon: Lightbulb,  color: 'text-amber-400',  bg: 'bg-amber-500/15 border-amber-500/30', label: 'Agent 4 · Recommender' },
];

const severityColors: Record<string, string> = {
  High:   'bg-rose-500/15 text-rose-400 border-rose-500/20',
  Medium: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  Low:    'bg-emerald-500/15 text-emerald-400 border-emerald-500/20',
};

function TypingText({ text }: { text: string }) {
  const [displayed, setDisplayed] = React.useState('');
  React.useEffect(() => {
    setDisplayed('');
    let i = 0;
    const timer = setInterval(() => {
      setDisplayed(text.slice(0, i + 1));
      i++;
      if (i >= text.length) clearInterval(timer);
    }, 10);
    return () => clearInterval(timer);
  }, [text]);
  return <span>{displayed}</span>;
}

export function AgentConsole({ data, type = 'workbook' }: { data: any; type?: 'workbook' | 'dashboard' }) {
  const [isRunning, setIsRunning] = useState(false);
  const [steps, setSteps] = useState<AgentStep[]>(
    PIPELINE_STEPS.map(s => ({ step: s.key, status: 'idle', output: null }))
  );
  const [result, setResult] = useState<AgentResult>({ classification: null, risks: [], recommendations: [] });
  const [isDone, setIsDone] = useState(false);
  const [expandedStep, setExpandedStep] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const resetState = () => {
    setSteps(PIPELINE_STEPS.map(s => ({ step: s.key, status: 'idle', output: null })));
    setResult({ classification: null, risks: [], recommendations: [] });
    setIsDone(false);
    setError(null);
    setExpandedStep(null);
  };

  const runAgents = () => {
    resetState();
    setIsRunning(true);
    if (esRef.current) esRef.current.close();

    // Build query params
    const worksheets = type === 'workbook'
      ? (data.dashboards?.flatMap((d: any) => d.worksheets || []) || [])
      : (data.worksheets || []);
    const datasources = type === 'workbook'
      ? (data.datasources?.map((ds: any) => ds.name) || [])
      : [];
    const name = type === 'workbook' ? (data.source_file || '') : (data.name || '');
    const calcCount = type === 'workbook'
      ? (data.datasources?.reduce((a: number, ds: any) => a + (ds.calculated_fields?.length || 0), 0) || 0)
      : 0;

    const params = new URLSearchParams({
      dashboard_name: name,
      worksheets: worksheets.join('|||'),
      datasources: datasources.join('|||'),
      calc_fields_count: String(calcCount),
    });

    const es = new EventSource(`${API_BASE_URL}/api/v1/agent/analyze/stream?${params}`);
    esRef.current = es;

    es.onmessage = (event) => {
      const parsed = JSON.parse(event.data);
      const { event: evtType, data: evtData } = parsed;

      if (evtType === 'step') {
        setSteps(prev => prev.map(s =>
          s.step === evtData.step
            ? { ...s, status: 'done', output: evtData.output }
            : s.status === 'idle' && prev.findIndex(x => x.step === evtData.step) + 1 === prev.findIndex(x => x.status === 'idle')
              ? { ...s, status: 'running' }
              : s
        ));
        // Mark next step as running
        setSteps(prev => {
          const doneIdx = prev.findIndex(s => s.step === evtData.step);
          if (doneIdx >= 0 && doneIdx < prev.length - 1) {
            return prev.map((s, i) => i === doneIdx + 1 ? { ...s, status: 'running' } : s);
          }
          return prev;
        });
      } else if (evtType === 'classification') {
        setResult(prev => ({ ...prev, classification: evtData }));
      } else if (evtType === 'risks') {
        setResult(prev => ({ ...prev, risks: evtData }));
      } else if (evtType === 'recommendations') {
        setResult(prev => ({ ...prev, recommendations: evtData }));
      } else if (evtType === 'done') {
        setIsDone(true);
        setIsRunning(false);
        es.close();
      } else if (evtType === 'error') {
        setError(evtData);
        setIsRunning(false);
        es.close();
      }
    };

    es.onerror = () => {
      setError('Connection to AI backend lost. Make sure the FastAPI server is running.');
      setIsRunning(false);
      es.close();
    };

    // Mark first step as running immediately
    setSteps(prev => prev.map((s, i) => i === 0 ? { ...s, status: 'running' } : s));
  };

  const hasStarted = steps.some(s => s.status !== 'idle');

  return (
    <div className="space-y-4">
      {/* Launch button — shown when not started */}
      {!hasStarted && (
        <div className="flex flex-col items-center justify-center py-8 border-2 border-dashed border-border rounded-2xl bg-card/40 gap-4">
          <div className="w-12 h-12 rounded-2xl bg-primary/10 border border-primary/20 flex items-center justify-center">
            <Brain className="w-6 h-6 text-primary" />
          </div>
          <div className="text-center">
            <h3 className="font-semibold text-foreground">AI Governance Agent Pipeline</h3>
            <p className="text-sm text-muted-foreground mt-1 max-w-sm">
              4 sequential agents will analyze this {type} in real time
            </p>
          </div>
          <button
            onClick={runAgents}
            className="flex items-center gap-2 px-5 py-2.5 bg-primary text-primary-foreground rounded-xl font-semibold text-sm hover:bg-primary/90 transition-colors shadow-lg shadow-primary/20"
          >
            <Play className="w-4 h-4" />
            Launch Agent Pipeline
          </button>
        </div>
      )}

      {/* Live Pipeline — horizontal rail */}
      {hasStarted && (
        <Card>
          <CardHeader className="pb-3 border-b border-border">
            <CardTitle className="text-sm flex items-center gap-2">
              <div className={`w-2 h-2 rounded-full ${isRunning ? 'bg-emerald-400 animate-pulse' : 'bg-emerald-400'}`} />
              Agent Pipeline · {isRunning ? 'Live Execution' : 'Complete'}
              {!isRunning && (
                <button onClick={runAgents} className="ml-auto text-xs text-muted-foreground hover:text-foreground flex items-center gap-1">
                  <Play className="w-3 h-3" /> Re-run
                </button>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="p-4">
            {/* Pipeline visual */}
            <div className="flex items-start gap-0 mb-4">
              {PIPELINE_STEPS.map((def, i) => {
                const stepState = steps[i];
                const Icon = def.icon;
                const isActive = stepState.status === 'running';
                const isDoneStep = stepState.status === 'done';
                const isIdle = stepState.status === 'idle';
                return (
                  <React.Fragment key={i}>
                    <button
                      onClick={() => isDoneStep && setExpandedStep(expandedStep === i ? null : i)}
                      className={`flex flex-col items-center gap-2 flex-1 group ${isDoneStep ? 'cursor-pointer' : 'cursor-default'}`}
                    >
                      {/* Icon bubble */}
                      <div className={`w-10 h-10 rounded-xl border-2 flex items-center justify-center transition-all duration-500 ${
                        isDoneStep ? `${def.bg} scale-100` :
                        isActive ? 'bg-primary/20 border-primary animate-pulse scale-105' :
                        'bg-muted/30 border-muted scale-95 opacity-50'
                      }`}>
                        {isDoneStep ? (
                          <CheckCircle2 className={`w-5 h-5 ${def.color}`} />
                        ) : isActive ? (
                          <Loader2 className="w-5 h-5 text-primary animate-spin" />
                        ) : (
                          <Icon className="w-5 h-5 text-muted-foreground/40" />
                        )}
                      </div>
                      {/* Label */}
                      <div className="text-center">
                        <p className={`text-[10px] font-bold uppercase tracking-wider ${isDoneStep ? def.color : isActive ? 'text-primary' : 'text-muted-foreground/40'}`}>
                          {def.label.split(' · ')[0]}
                        </p>
                        <p className={`text-[9px] ${isDoneStep || isActive ? 'text-muted-foreground' : 'text-muted-foreground/30'}`}>
                          {def.label.split(' · ')[1]}
                        </p>
                      </div>
                    </button>
                    {/* Connector line */}
                    {i < PIPELINE_STEPS.length - 1 && (
                      <div className="flex-shrink-0 flex items-center mt-5">
                        <div className={`h-0.5 w-8 transition-all duration-700 ${steps[i].status === 'done' ? 'bg-emerald-500' : 'bg-muted/30'}`} />
                        <div className={`w-0 h-0 border-t-4 border-b-4 border-l-4 border-transparent transition-all duration-700 ${steps[i].status === 'done' ? 'border-l-emerald-500' : 'border-l-muted/30'}`} />
                      </div>
                    )}
                  </React.Fragment>
                );
              })}
            </div>

            {/* Expanded step detail */}
            {expandedStep !== null && steps[expandedStep]?.output && (
              <div className={`mt-2 p-3 rounded-xl border ${PIPELINE_STEPS[expandedStep].bg} text-xs font-mono leading-relaxed animate-in fade-in duration-200`}>
                <p className={`text-[10px] font-bold uppercase tracking-wider mb-1 ${PIPELINE_STEPS[expandedStep].color}`}>
                  {PIPELINE_STEPS[expandedStep].label} Output
                </p>
                <TypingText text={steps[expandedStep].output!} />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Results */}
      {isDone && (
        <div className="space-y-3 animate-in fade-in duration-500">
          {result.classification && (
            <Card className="border-violet-500/20 bg-violet-500/5">
              <CardContent className="pt-4 pb-4 flex items-start gap-4">
                <div className="flex-1">
                  <p className="text-[10px] font-bold uppercase tracking-wider text-violet-400 mb-1">AI Classification</p>
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <span className="px-2.5 py-0.5 rounded-full bg-violet-500/20 text-violet-400 text-xs font-bold border border-violet-500/30">
                      {result.classification.domain}
                    </span>
                    {result.classification.is_real_ai ? (
                      <span className="px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 text-[9px] font-bold border border-emerald-500/20 uppercase tracking-wider flex items-center gap-1">
                        Live AI Summary
                      </span>
                    ) : (
                      <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-400 text-[9px] font-bold border border-amber-500/20 uppercase tracking-wider flex items-center gap-1">
                        ⚙️ Governance Fallback
                      </span>
                    )}
                    <span className="text-xs text-muted-foreground ml-auto">Complexity: {result.classification.complexity.toFixed(1)}/10</span>
                  </div>
                  <p className="text-sm text-muted-foreground">{result.classification.summary}</p>
                </div>
              </CardContent>
            </Card>
          )}

          {result.risks.length > 0 && (
            <Card>
              <CardHeader className="pb-2 pt-3 border-b border-border">
                <CardTitle className="text-xs uppercase tracking-widest text-muted-foreground">Governance Risks</CardTitle>
              </CardHeader>
              <CardContent className="p-3 space-y-2">
                {result.risks.map((risk, i) => (
                  <div key={i} className="flex items-start gap-2.5 p-2.5 rounded-lg border border-border bg-muted/20">
                    <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold border flex-shrink-0 ${severityColors[risk.severity] || severityColors['Low']}`}>
                      {risk.severity}
                    </span>
                    <div>
                      <p className="text-xs font-semibold text-foreground">{risk.risk_type}</p>
                      <p className="text-xs text-muted-foreground mt-0.5">{risk.description}</p>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {result.recommendations.length > 0 && (
            <Card className="border-emerald-500/20 bg-emerald-500/5">
              <CardHeader className="pb-2 pt-3 border-b border-border">
                <CardTitle className="text-xs uppercase tracking-widest text-emerald-400">Recommendations</CardTitle>
              </CardHeader>
              <CardContent className="p-3 space-y-1.5">
                {result.recommendations.map((rec, i) => (
                  <p key={i} className="text-xs text-muted-foreground leading-relaxed">{rec}</p>
                ))}
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {error && (
        <div className="p-3 rounded-xl bg-destructive/10 border border-destructive/30 text-destructive text-xs">
          {error}
        </div>
      )}
    </div>
  );
}