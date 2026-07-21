import { API_BASE_URL } from '@/config';
import React, { useEffect, useState } from 'react';
import { ReactFlow, MiniMap, Controls, Background, useNodesState, useEdgesState, MarkerType, Handle, Position } from '@xyflow/react';
import '@xyflow/react/dist/style.css';
// @ts-ignore
import dagre from 'dagre';
import { Loader2, AlertCircle } from 'lucide-react';

const nodeWidth = 200;
const nodeHeight = 52;
const tableNodeWidth = 220;

const getLayoutedElements = (nodes: any[], edges: any[], direction = 'LR') => {
  const isHorizontal = direction === 'LR';
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: direction, ranksep: 100, nodesep: 60 });

  nodes.forEach((node) => {
    const w = node.data?.isTable ? tableNodeWidth : nodeWidth;
    let h = nodeHeight;
    if (node.data?.isTable) {
      if (node.data?.columns?.length > 0) h += node.data.columns.length * 20 + 10;
      if (node.data?.rows_preview?.length > 0) h += node.data.rows_preview.length * 16 + 30;
    }
    g.setNode(node.id, { width: w, height: h });
  });
  edges.forEach((edge) => {
    g.setEdge(edge.source, edge.target);
  });

  dagre.layout(g);

  return {
    nodes: nodes.map((node) => {
      const pos = g.node(node.id);
      return {
        ...node,
        targetPosition: isHorizontal ? 'left' : 'top',
        sourcePosition: isHorizontal ? 'right' : 'bottom',
        position: { x: pos.x - (node.data?.isTable ? tableNodeWidth : nodeWidth) / 2, y: pos.y - nodeHeight / 2 },
      };
    }),
    edges,
  };
};

// ── Node type → visual config ────────────────────────────────────────────────
const nodeConfig: Record<string, { bg: string; border: string; text: string; dot: string }> = {
  Workbook:       { bg: '#1e293b', border: '#475569', text: '#94a3b8', dot: '#475569' },
  Dashboard:      { bg: '#1e3a5f', border: '#3b82f6', text: '#93c5fd', dot: '#3b82f6' },
  Worksheet:      { bg: '#14532d', border: '#22c55e', text: '#86efac', dot: '#22c55e' },
  'Worksheet (Duplicate)': { bg: '#451a03', border: '#f97316', text: '#fdba74', dot: '#f97316' },
  Datasource:     { bg: '#431407', border: '#f59e0b', text: '#fcd34d', dot: '#f59e0b' },
  Table:          { bg: '#2e1065', border: '#8b5cf6', text: '#c4b5fd', dot: '#8b5cf6' },
};

// Join type → edge color
const joinColors: Record<string, string> = {
  inner: '#22c55e',
  left:  '#3b82f6',
  right: '#f59e0b',
  full:  '#ec4899',
};

function buildNode(n: any) {
  const cfg = nodeConfig[n.type] || nodeConfig['Workbook'];
  const isTable = n.type === 'Table';
  const cols: string[] = n.columns || [];
  const rows: string[][] = n.rows_preview || [];
  const width = isTable ? tableNodeWidth : nodeWidth;
  return {
    id: n.id,
    data: {
      isTable,
      columns: cols,
      label: (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: cfg.dot, flexShrink: 0 }} />
            <div style={{ overflow: 'hidden' }}>
              <div style={{ fontSize: 11, color: cfg.text, opacity: 0.7, textTransform: 'uppercase', letterSpacing: 1 }}>{n.type}</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: '#f1f5f9', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: width - 52 }}>{n.label}</div>
            </div>
          </div>
          {isTable && cols.length > 0 && (
            <div style={{ paddingTop: 6, marginTop: 4, display: 'flex', flexDirection: 'column', gap: 4 }}>
              {cols.map((col: string) => (
                <div key={col} style={{ position: 'relative', display: 'flex', alignItems: 'center', gap: 6, padding: '6px 10px', background: '#0f172a', border: '1px solid #334155', borderRadius: 6, boxShadow: 'inset 0 1px 2px rgba(0,0,0,0.2)' }}>
                  <Handle type="target" position={Position.Left} id={col} style={{ left: -14, width: 8, height: 8, background: '#3b82f6', border: '2px solid #020817' }} />
                  <div style={{ width: 4, height: 4, borderRadius: '50%', background: '#8b5cf6', flexShrink: 0 }} />
                  <span style={{ fontSize: 11, color: '#e2e8f0', fontFamily: 'monospace', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: width - 30 }}>{col}</span>
                  <Handle type="source" position={Position.Right} id={col} style={{ right: -14, width: 8, height: 8, background: '#22c55e', border: '2px solid #020817' }} />
                </div>
              ))}
            </div>
          )}

          {isTable && rows.length > 0 && (
            <div style={{ borderTop: '1px solid #1e293b', marginTop: 4, paddingTop: 4 }}>
              <div style={{ fontSize: 9, color: '#64748b', textTransform: 'uppercase', marginBottom: 4, letterSpacing: 1 }}>Data Preview (5 Rows)</div>
              <div style={{ overflowX: 'auto', maxWidth: width - 24 }}>
                <table style={{ width: '100%', fontSize: 9, color: '#94a3b8', borderCollapse: 'collapse' }}>
                  <tbody>
                    {rows.map((row, rIdx) => (
                      <tr key={rIdx} style={{ borderBottom: '1px solid #1e293b' }}>
                        {row.map((cell, cIdx) => (
                          <td key={cIdx} style={{ padding: '2px 4px', whiteSpace: 'nowrap', maxWidth: 60, overflow: 'hidden', textOverflow: 'ellipsis' }}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      )
    },
    style: {
      background: cfg.bg,
      border: `1.5px solid ${cfg.border}`,
      borderRadius: 10,
      padding: '8px 12px',
      width,
      boxShadow: `0 0 16px ${cfg.border}33`,
    },
  };
}

function buildEdge(e: any) {
  const isJoin = e.edge_type === 'join';
  const joinColor = joinColors[e.join_type] || '#64748b';
  const color = isJoin ? joinColor : '#334155';

  // For join edges, show 2-line label: "INNER JOIN\ncol_a = col_b"
  const labelLines = (e.label || '').split('\n');

  return {
    id: e.id,
    source: e.source,
    target: e.target,
    sourceHandle: isJoin ? e.left_column : undefined,
    targetHandle: isJoin ? e.right_column : undefined,
    animated: isJoin,
    type: isJoin ? 'smoothstep' : 'default',
    style: { stroke: color, strokeWidth: isJoin ? 2.5 : 1.5, strokeDasharray: isJoin ? '0' : '4 3' },
    markerEnd: { type: MarkerType.ArrowClosed, color },
    label: isJoin ? (
      <div style={{ textAlign: 'center', lineHeight: 1.4, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        <div style={{ fontWeight: 800, fontSize: 10, color: joinColor, textTransform: 'uppercase', letterSpacing: 1.5, background: `${joinColor}15`, padding: '2px 6px', borderRadius: 4, border: `1px solid ${joinColor}30` }}>
          {labelLines[0]}
        </div>
        {labelLines[1] && labelLines[1].includes('=') && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 6, background: '#0f172a', padding: '4px 8px', borderRadius: 6, border: '1px solid #334155', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.5)' }}>
            <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#f8fafc', fontWeight: 600 }}>{labelLines[1].split('=')[0].trim()}</span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#3b82f6" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
            <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#f8fafc', fontWeight: 600 }}>{labelLines[1].split('=')[1].trim()}</span>
          </div>
        )}
      </div>
    ) : e.label,
    labelStyle: { fontSize: 10, fill: '#94a3b8', fontWeight: 600 },
    labelBgStyle: { fill: 'transparent' },
    labelBgPadding: [0, 0],
  };
}

export function LineageGraph({ dashboardName, workbookName, viewType = 'full' }: { dashboardName?: string; workbookName?: string; viewType?: 'full' | 'worksheets' | 'tables' }) {
  const [nodes, setNodes, onNodesChange] = useNodesState<any>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<any>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [joinCount, setJoinCount] = useState(0);

  useEffect(() => {
    const fetchLineage = async () => {
      try {
        setIsLoading(true);
        const url = dashboardName
          ? `${API_BASE_URL}/api/v1/lineage/${encodeURIComponent(dashboardName)}`
          : `${API_BASE_URL}/api/v1/lineage/workbook/${encodeURIComponent(workbookName!)}?view_type=${viewType}`;
        const res = await fetch(url);
        if (!res.ok) throw new Error('Failed to fetch lineage data');
        const data = await res.json();

        const formattedNodes = data.nodes.map(buildNode);
        const formattedEdges = data.edges.map(buildEdge);
        setJoinCount(data.edges.filter((e: any) => e.edge_type === 'join').length);

        const { nodes: ln, edges: le } = getLayoutedElements(formattedNodes, formattedEdges, 'LR');
        setNodes(ln);
        setEdges(le);
        setError(null);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };

    if (dashboardName || workbookName) fetchLineage();
  }, [dashboardName, workbookName, viewType, setNodes, setEdges]);

  if (isLoading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 500, background: '#020817', borderRadius: 12, border: '1px solid #1e293b' }}>
        <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
        <p style={{ color: '#94a3b8', marginTop: 16, fontWeight: 600 }}>Building Lineage Graph...</p>
        <p style={{ color: '#475569', marginTop: 4, fontSize: 13 }}>Tracing joins, datasources & calculated fields</p>
      </div>
    );
  }

  if (error || nodes.length === 0) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: 500, background: '#020817', borderRadius: 12, border: '1px solid #1e293b' }}>
        <AlertCircle className="w-10 h-10 text-rose-500 mb-3" />
        <p style={{ color: '#f87171', fontWeight: 600 }}>Lineage unavailable</p>
        <p style={{ color: '#64748b', fontSize: 13, marginTop: 4, textAlign: 'center', maxWidth: 340 }}>
          {error || 'The dashboard has no lineage data yet. Upload and parse the workbook file first.'}
        </p>
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', height: 580, background: '#020817', borderRadius: 12, border: '1px solid #1e293b', overflow: 'hidden' }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        minZoom={0.15}
        colorMode="dark"
      >
        <MiniMap nodeStrokeWidth={2} zoomable pannable style={{ background: '#0f172a', border: '1px solid #1e293b' }} />
        <Controls style={{ background: '#0f172a', border: '1px solid #1e293b', borderRadius: 8 }} />
        <Background color="#1e293b" gap={24} size={1} />
      </ReactFlow>

      {/* Legend */}
      <div style={{ position: 'absolute', top: 12, left: 12, background: 'rgba(2,8,23,0.9)', border: '1px solid #1e293b', borderRadius: 10, padding: '12px 14px', backdropFilter: 'blur(8px)' }}>
        <p style={{ fontSize: 10, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 8 }}>Node Types</p>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '5px 16px' }}>
          {Object.entries(nodeConfig).map(([type, cfg]) => (
            <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: 2, background: cfg.border }} />
              <span style={{ fontSize: 11, color: '#94a3b8' }}>{type}</span>
            </div>
          ))}
        </div>
        {joinCount > 0 && (
          <>
            <div style={{ borderTop: '1px solid #1e293b', margin: '10px 0' }} />
            <p style={{ fontSize: 10, fontWeight: 700, color: '#64748b', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 6 }}>Join Types</p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(joinColors).map(([type, color]) => (
                <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                  <div style={{ width: 16, height: 2.5, background: color, borderRadius: 2 }} />
                  <span style={{ fontSize: 11, color: '#94a3b8', textTransform: 'capitalize' }}>{type} Join</span>
                </div>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  );
}