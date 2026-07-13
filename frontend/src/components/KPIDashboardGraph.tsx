import { API_BASE_URL } from '@/config';
import { useEffect, useRef, useState } from 'react';
import * as d3 from 'd3';
import { Loader2, AlertCircle, Sparkles, Maximize2, X, TrendingUp } from 'lucide-react';
interface NodeData extends d3.SimulationNodeDatum {
  id: string;
  group: string;
  label: string;
  definition?: string;
  complexity?: number;
}
interface LinkData extends d3.SimulationLinkDatum<NodeData> {
  source: string | NodeData;
  target: string | NodeData;
  label: string;
}
interface KPIDashboardGraphProps {
  dashboards: string;
  height?: string;
  isMaximizedView?: boolean;
  onMinimize?: () => void;
  graphData?: { nodes: any[]; links: any[] } | null;
}
export function KPIDashboardGraph({ dashboards, height, isMaximizedView = false, onMinimize, graphData }: KPIDashboardGraphProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [aiSummary, setAiSummary] = useState<string | null>(null);
  const [isLoadingSummary, setIsLoadingSummary] = useState(false);
  const [showSummary, setShowSummary] = useState(true);
  const [isMaximized, setIsMaximized] = useState(false);
  const [activeHighlight, setActiveHighlight] = useState<string | null>('common-kpi');
  const highlightGraphRef = useRef<((type: string | null) => void) | null>(null);
  useEffect(() => {
    let simulation: d3.Simulation<NodeData, LinkData>;
    const fetchDataAndDraw = async () => {
      try {
        setIsLoading(true);
        setError(null);
        let data;
        if (graphData) {
          data = graphData;
        } else {
          // Add cache-busting timestamp to ensure the browser doesn't serve old fuzzy-matched results
          const timestamp = new Date().getTime();
          const res = await fetch(`${API_BASE_URL}/api/v1/kpi-graph/data?dashboards=${encodeURIComponent(dashboards)}&_t=${timestamp}`);
          if (!res.ok) throw new Error('Failed to fetch KPI graph data');
          data = await res.json();
        }
        if (!data.nodes || data.nodes.length === 0) {
          throw new Error('No graph data found for the selected dashboards.');
        }
        drawGraph(data.nodes, data.links);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setIsLoading(false);
      }
    };
    const drawGraph = (nodes: NodeData[], links: LinkData[]) => {
      if (!svgRef.current || !containerRef.current) return;
      const width = containerRef.current.clientWidth;
      const height = containerRef.current.clientHeight || 600;
      const svg = d3.select(svgRef.current);
      svg.selectAll('*').remove();
      // Setup zoom
      const g = svg.append('g');
      const zoom = d3.zoom<SVGSVGElement, unknown>()
        .scaleExtent([0.1, 4])
        .on('zoom', (event) => {
          g.attr('transform', event.transform);
        });
      svg.call(zoom);
      // Define colors
      const colorMap: Record<string, string> = {
        'Dashboard': '#3b82f6', // blue
        'KPI': '#10b981', // green
        'Business Area': '#8b5cf6', // purple
        'User Group': '#f59e0b', // amber
        'Table': '#ef4444', // red
        'Granularity Level': '#8b4513', // brown
        'Access Recency': '#ec4899', // pink
        'Access Frequency': '#ec4899' // fallback
      };
      // Simulation setup
      simulation = d3.forceSimulation<NodeData, LinkData>(nodes)
        .force('link', d3.forceLink<NodeData, LinkData>(links).id(d => d.id).distance(120))
        .force('charge', d3.forceManyBody().strength(-400))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collide', d3.forceCollide().radius(40));
      // Draw links
      const link = g.append('g')
        .attr('stroke', '#334155')
        .attr('stroke-opacity', 0.6)
        .attr('stroke-width', 2)
        .selectAll('line')
        .data(links)
        .join('line');
      // Link labels
      const linkLabel = g.append('g')
        .selectAll('text')
        .data(links)
        .join('text')
        .attr('font-size', '10px')
        .attr('fill', '#94a3b8')
        .attr('text-anchor', 'middle')
        .text(d => d.label);
      // Node groups
      const node = g.append('g')
        .selectAll('g')
        .data(nodes)
        .join('g')
        .call(d3.drag<any, any>()
          .on('start', dragstarted)
          .on('drag', dragged)
          .on('end', dragended) as any
        );
      // Draw nodes (circles)
      node.append('circle')
        .attr('r', d => d.group === 'Dashboard' ? 24 : 16)
        .attr('fill', d => colorMap[d.group] || '#64748b')
        .attr('stroke', '#020817')
        .attr('stroke-width', 2);
      // Draw text
      node.append('text')
        .text(d => d.label)
        .attr('x', 0)
        .attr('y', d => d.group === 'Dashboard' ? 35 : 25)
        .attr('text-anchor', 'middle')
        .attr('font-size', '12px')
        .attr('font-weight', d => d.group === 'Dashboard' ? 'bold' : 'normal')
        .attr('fill', '#f1f5f9')
        .style('pointer-events', 'none')
        // Wrap text roughly
        .each(function(d) {
           const el = d3.select(this);
           const words = d.label.split(/\s+/);
           if (words.length > 2) {
             el.text('');
             el.append('tspan').text(words.slice(0, 2).join(' ')).attr('x', 0).attr('dy', 0);
             el.append('tspan').text(words.slice(2).join(' ')).attr('x', 0).attr('dy', 14);
           }
        });
      // Tooltips
      const tooltip = d3.select(containerRef.current)
        .append('div')
        .attr('class', 'absolute hidden bg-slate-900 border border-slate-700 text-slate-200 p-2 rounded shadow-lg text-xs pointer-events-none z-50 max-w-xs')
        .style('opacity', 0);
      node.on('mouseover', (event, d) => {
        tooltip.transition().duration(200).style('opacity', 1).style('display', 'block');
        const defHtml = d.definition ? '<div class="text-slate-400">' + d.definition + '</div>' : '';
        tooltip.html('<div class="font-bold mb-1">' + d.group + ': ' + d.label + '</div>' + defHtml)
          .style('left', (event.pageX + 15) + 'px')
          .style('top', (event.pageY - 15) + 'px');
      }).on('mousemove', (event) => {
        tooltip.style('left', (event.pageX + 15) + 'px')
               .style('top', (event.pageY - 15) + 'px');
      }).on('mouseout', () => {
        tooltip.transition().duration(500).style('opacity', 0).on('end', function() { d3.select(this).style('display', 'none'); });
      });
        // Node Click Highlighting
      node.on('click', (event, d) => {
        setActiveHighlight(null);
        link.attr('stroke-opacity', 0.1).attr('stroke', '#334155');
        node.style('opacity', 0.2);
        
        const connectedNodeIds = new Set<string>([d.id]);
        const expectedGranularities = new Set<string>();
        
        link.filter((l: any) => {
          const isConnected = l.source.id === d.id || l.target.id === d.id;
          if (isConnected) {
            connectedNodeIds.add(l.source.id);
            connectedNodeIds.add(l.target.id);
            if (l.granularity) {
                expectedGranularities.add(l.granularity);
            }
          }
          return isConnected;
        })
        .attr('stroke-opacity', 1)
        .attr('stroke', '#3b82f6');
        
        // If we are a Dashboard and we connected to a KPI, we need to explicitly highlight the Granularity node connected to that KPI
        if (d.group === 'Dashboard' && expectedGranularities.size > 0) {
            link.filter((l: any) => {
                if ((l.source.group === 'KPI' || l.target.group === 'KPI') && 
                    (l.source.group === 'Granularity Level' || l.target.group === 'Granularity Level')) {
                    
                    const granNode = l.source.group === 'Granularity Level' ? l.source : l.target;
                    const kpiNode = l.source.group === 'KPI' ? l.source : l.target;
                    
                    if (connectedNodeIds.has(kpiNode.id) && expectedGranularities.has(granNode.label)) {
                        connectedNodeIds.add(granNode.id);
                        return true;
                    }
                }
                return false;
            })
            .attr('stroke-opacity', 1)
            .attr('stroke', '#3b82f6');
        }
        // If we are a Granularity Level, we explicitly highlight the Dashboards connected to the KPIs we are connected to.
        if (d.group === 'Granularity Level') {
            link.filter((l: any) => {
                if ((l.source.group === 'KPI' || l.target.group === 'KPI') && 
                    (l.source.group === 'Dashboard' || l.target.group === 'Dashboard')) {
                    
                    const kpiNode = l.source.group === 'KPI' ? l.source : l.target;
                    const dashboardNode = l.source.group === 'Dashboard' ? l.source : l.target;
                    
                    if (connectedNodeIds.has(kpiNode.id) && l.granularity === d.label) {
                        connectedNodeIds.add(dashboardNode.id);
                        return true;
                    }
                }
                return false;
            })
            .attr('stroke-opacity', 1)
            .attr('stroke', '#3b82f6');
        }
        node.filter((n: any) => connectedNodeIds.has(n.id))
            .style('opacity', 1);
        event.stopPropagation();
      });
      svg.on('click', () => {
         setActiveHighlight(null);
         link.attr('stroke-opacity', 0.6).attr('stroke', '#334155');
         node.style('opacity', 1);
      });
      // External Highlight Function
      highlightGraphRef.current = (type: string | null) => {
        // Reset styles first
        link.attr('stroke-opacity', 0.6).attr('stroke', '#334155');
        node.style('opacity', 1);
        node.selectAll('circle')
          .attr('stroke', '#020817')
          .attr('stroke-width', 2);

        if (!type) return;

        // Dim everything
        link.attr('stroke-opacity', 0.1);
        node.style('opacity', 0.25);

        const targetNodeIds = new Set<string>();

        if (type === 'access-recency') {
          nodes.forEach(n => { if (n.group.toLowerCase().includes('access')) targetNodeIds.add(n.id); });
        } else if (type === 'granularity-level') {
          nodes.forEach(n => { if (n.group.toLowerCase().includes('granular')) targetNodeIds.add(n.id); });
        } else if (type === 'user-group') {
          nodes.forEach(n => { if (n.group.toLowerCase().includes('user')) targetNodeIds.add(n.id); });
        } else if (type === 'tables') {
          nodes.forEach(n => { if (n.group.toLowerCase().includes('table')) targetNodeIds.add(n.id); });
        } else if (type === 'common-kpi') {
          // Find all non-Dashboard nodes that connect to more than one Dashboard node
          nodes.forEach(n => {
            if (n.group !== 'Dashboard') {
              const connectedLinks = links.filter(l => {
                const srcId = typeof l.source === 'object' ? (l.source as any).id : l.source;
                const tgtId = typeof l.target === 'object' ? (l.target as any).id : l.target;
                return srcId === n.id || tgtId === n.id;
              });

              const distinctDashboards = new Set<string>();
              connectedLinks.forEach(l => {
                const srcNode = typeof l.source === 'object' ? (l.source as any) : nodes.find(x => x.id === l.source);
                const tgtNode = typeof l.target === 'object' ? (l.target as any) : nodes.find(x => x.id === l.target);
                if (srcNode && srcNode.group === 'Dashboard') distinctDashboards.add(srcNode.id);
                if (tgtNode && tgtNode.group === 'Dashboard') distinctDashboards.add(tgtNode.id);
              });

              if (distinctDashboards.size > 1) {
                targetNodeIds.add(n.id);
              }
            }
          });
        } else if (type === 'kpi') {
          nodes.forEach(n => { if (n.group === 'KPI') targetNodeIds.add(n.id); });
        }

        const connectedNodeIds = new Set<string>(targetNodeIds);

        // Highlight target nodes and their circle outlines
        node.filter((n: any) => targetNodeIds.has(n.id))
          .style('opacity', 1)
          .selectAll('circle')
          .attr('stroke', type === 'common-kpi' ? '#f59e0b' : type === 'kpi' ? '#10b981' : '#3b82f6')
          .attr('stroke-width', 3);

        // Highlight links connected to target nodes
        link.filter((l: any) => {
          const srcId = typeof l.source === 'object' ? (l.source as any).id : l.source;
          const tgtId = typeof l.target === 'object' ? (l.target as any).id : l.target;
          const isConnected = targetNodeIds.has(srcId) || targetNodeIds.has(tgtId);
          if (isConnected) {
            connectedNodeIds.add(srcId);
            connectedNodeIds.add(tgtId);
          }
          return isConnected;
        })
        .attr('stroke-opacity', 1)
        .attr('stroke', type === 'common-kpi' ? '#f59e0b' : type === 'kpi' ? '#10b981' : '#3b82f6');

        if (type === 'granularity-level') {
            link.filter((l: any) => {
                const srcNode = typeof l.source === 'object' ? (l.source as any) : nodes.find(x => x.id === l.source);
                const tgtNode = typeof l.target === 'object' ? (l.target as any) : nodes.find(x => x.id === l.target);
                if (srcNode && tgtNode && (srcNode.group === 'KPI' || tgtNode.group === 'KPI') && 
                    (srcNode.group === 'Dashboard' || tgtNode.group === 'Dashboard')) {
                    
                    const kpiNode = srcNode.group === 'KPI' ? srcNode : tgtNode;
                    const dashboardNode = srcNode.group === 'Dashboard' ? srcNode : tgtNode;
                    
                    if (connectedNodeIds.has(kpiNode.id)) {
                        let matchesGranularity = false;
                        targetNodeIds.forEach(targetId => {
                            const n = nodes.find(n => n.id === targetId);
                            if (n && l.granularity === n.label) matchesGranularity = true;
                        });
                        
                        if (matchesGranularity) {
                            connectedNodeIds.add(dashboardNode.id);
                            return true;
                        }
                    }
                }
                return false;
            })
            .attr('stroke-opacity', 1)
            .attr('stroke', '#3b82f6');
        }

        // Additionally highlight all connected nodes (dashboards, etc.) to make them visible
        node.filter((n: any) => connectedNodeIds.has(n.id))
          .style('opacity', 1);
      };

      // Tick function to update positions
      simulation.on('tick', () => {
        link
          .attr('x1', d => (d.source as NodeData).x!)
          .attr('y1', d => (d.source as NodeData).y!)
          .attr('x2', d => (d.target as NodeData).x!)
          .attr('y2', d => (d.target as NodeData).y!);
        linkLabel
          .attr('x', d => ((d.source as NodeData).x! + (d.target as NodeData).x!) / 2)
          .attr('y', d => ((d.source as NodeData).y! + (d.target as NodeData).y!) / 2);
        node.attr('transform', d => `translate(${d.x},${d.y})`);
      });

      function dragstarted(event: any) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        event.subject.fx = event.subject.x;
        event.subject.fy = event.subject.y;
      }
      
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      function dragged(event: any) {
        event.subject.fx = event.x;
        event.subject.fy = event.y;
      }
      
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      function dragended(event: any) {
        if (!event.active) simulation.alphaTarget(0);
        // Do not clear fx and fy so the node stays pinned
      }

      // Run initial highlight if activeHighlight is set
      if (activeHighlight) {
        highlightGraphRef.current?.(activeHighlight);
      }
    };
    if (dashboards) {
      fetchDataAndDraw();
      
      const fetchSummary = async () => {
        setIsLoadingSummary(true);
        try {
          const res = await fetch(`${API_BASE_URL}/api/v1/kpi-graph/summary?dashboards=${encodeURIComponent(dashboards)}`);
          if (res.ok) {
            const data = await res.json();
            setAiSummary(data.summary);
          }
        } catch (err) {
          console.error("Failed to fetch AI summary:", err);
        } finally {
          setIsLoadingSummary(false);
        }
      };
      
      fetchSummary();
    }
    return () => {
      if (simulation) simulation.stop();
      d3.select(containerRef.current).selectAll('.absolute.hidden.bg-slate-900').remove(); // Cleanup tooltips
    };
  }, [dashboards]);
    const handleHighlightClick = async (type: string) => {
      const newHighlight = activeHighlight === type ? null : type;
      setActiveHighlight(newHighlight);
      highlightGraphRef.current?.(newHighlight);
      
      // Dynamic Summary Fetching
      setIsLoadingSummary(true);
      try {
        const timestamp = new Date().getTime();
        const focusType = newHighlight || 'all';
        const sumRes = await fetch(`${API_BASE_URL}/api/v1/kpi-graph/summary?dashboards=${encodeURIComponent(dashboards)}&focus_type=${focusType}&_t=${timestamp}`);
        if (sumRes.ok) {
          const sumData = await sumRes.json();
          setAiSummary(sumData.summary);
        } else {
          setAiSummary("Failed to fetch dynamic summary for this view.");
        }
      } catch (e) {
        setAiSummary("Error generating AI summary.");
      } finally {
        setIsLoadingSummary(false);
      }
    };
  return (
    <div className="flex flex-col gap-4 w-full">
      {/* Toolbar / Action Buttons Above */}
      <div className="flex flex-wrap items-center gap-3 w-full bg-slate-900 p-3 rounded-xl border border-slate-800 shadow-md">
        <span className="text-sm font-semibold text-slate-400 mr-2">Highlight Connections:</span>
        <button 
          onClick={() => handleHighlightClick('common-kpi')}
          className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${activeHighlight === 'common-kpi' ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.3)]' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
        >
          Common Matrices
        </button>
        <button 
          onClick={() => handleHighlightClick('kpi')}
          className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${activeHighlight === 'kpi' ? 'bg-emerald-500/20 border-emerald-500 text-emerald-400 shadow-[0_0_10px_rgba(16,185,129,0.3)]' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
        >
          KPI
        </button>
        <button 
          onClick={() => handleHighlightClick('tables')}
          className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${activeHighlight === 'tables' ? 'bg-red-500/20 border-red-500 text-red-400 shadow-[0_0_10px_rgba(239,68,68,0.3)]' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
        >
          Tables
        </button>
        <button 
          onClick={() => handleHighlightClick('user-group')}
          className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${activeHighlight === 'user-group' ? 'bg-amber-500/20 border-amber-500 text-amber-400 shadow-[0_0_10px_rgba(245,158,11,0.3)]' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
        >
          User Group
        </button>
        <button 
          onClick={() => handleHighlightClick('granularity-level')}
          className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${activeHighlight === 'granularity-level' ? 'bg-[#8b4513]/20 border-[#8b4513] text-[#cd853f] shadow-[0_0_10px_rgba(139,69,19,0.3)]' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
        >
          Granularity Level
        </button>
        <button 
          onClick={() => handleHighlightClick('access-recency')}
          className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${activeHighlight === 'access-recency' ? 'bg-pink-500/20 border-pink-500 text-pink-400 shadow-[0_0_10px_rgba(236,72,153,0.3)]' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
        >
          Access Recency
        </button>
        <div className="ml-auto flex items-center gap-2">
          <button 
            onClick={() => setShowSummary(!showSummary)}
            className={`px-4 py-2 rounded-lg text-[13px] font-semibold border transition-all shadow-sm flex items-center justify-center ${showSummary ? 'bg-indigo-500/20 border-indigo-500 text-indigo-400' : 'bg-slate-950 border-slate-700 text-slate-300 hover:bg-slate-800 hover:border-slate-500 hover:text-white'}`}
          >
            {showSummary ? 'Hide AI Summary' : 'Show AI Summary'}
          </button>
          {!isMaximizedView ? (
            <button 
              onClick={() => setIsMaximized(true)}
              className="px-4 py-2 bg-slate-950 border border-slate-700 hover:bg-slate-850 hover:border-slate-500 text-slate-300 hover:text-white rounded-lg text-[13px] font-semibold flex items-center gap-1.5 transition-all shadow-sm cursor-pointer"
            >
              <Maximize2 className="w-3.5 h-3.5" /> Open Full View
            </button>
          ) : (
            onMinimize && (
              <button 
                onClick={onMinimize}
                className="px-4 py-2 bg-rose-500/20 border border-rose-500 hover:bg-rose-600 hover:text-slate-950 text-rose-400 rounded-lg text-[13px] font-semibold flex items-center gap-1.5 transition-all shadow-sm cursor-pointer"
              >
                <X className="w-3.5 h-3.5" /> Close Full View
              </button>
            )
          )}
        </div>
      </div>
      {/* Main content side by side */}
      <div className="flex flex-row gap-4 w-full" style={{ height: height || '600px' }}>
        
        {/* Graph Area */}
        <div ref={containerRef} className={`relative ${showSummary ? 'w-[70%]' : 'w-full'} transition-all duration-500 h-full bg-slate-950 rounded-xl border border-slate-800 overflow-hidden shadow-xl`}>
          {isLoading && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-slate-950/80 backdrop-blur-sm">
              <Loader2 className="w-10 h-10 text-blue-500 animate-spin" />
              <p className="text-slate-400 mt-4 font-semibold">Building Network Graph...</p>
            </div>
          )}
          {error && (
            <div className="absolute inset-0 z-20 flex flex-col items-center justify-center bg-slate-950/90 backdrop-blur-sm">
              <AlertCircle className="w-10 h-10 text-rose-500 mb-3" />
              <p className="text-rose-400 font-semibold">Graph unavailable</p>
              <p className="text-slate-500 text-sm mt-2 text-center max-w-sm">{error}</p>
            </div>
          )}
          <svg ref={svgRef} className="w-full h-full cursor-grab active:cursor-grabbing" />
        
          {/* Legend */}
          <div className="absolute top-4 left-4 bg-slate-900/90 border border-slate-800 rounded-lg p-3 backdrop-blur-md z-10 pointer-events-none">
            <p className="text-[10px] font-bold text-slate-500 uppercase tracking-widest mb-2">Node Types</p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2">
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-blue-500" /><span className="text-xs text-slate-300">Dashboard</span></div>
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-emerald-500" /><span className="text-xs text-slate-300">KPI</span></div>
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-purple-500" /><span className="text-xs text-slate-300">Business Area</span></div>
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-amber-500" /><span className="text-xs text-slate-300">User Group</span></div>
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-red-500" /><span className="text-xs text-slate-300">Table</span></div>
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-[#8b4513]" /><span className="text-xs text-slate-300">Granularity Level</span></div>
              <div className="flex items-center gap-2"><div className="w-3 h-3 rounded-full bg-pink-500" /><span className="text-xs text-slate-300">Access Recency</span></div>
            </div>
          </div>
        </div>
        {/* AI Summary Card */}
        {showSummary && (
          <div className="w-[30%] animate-in slide-in-from-right-8 fade-in h-full bg-slate-900 border border-slate-800 rounded-xl p-5 relative overflow-y-auto shadow-lg flex flex-col">
            <div className="absolute top-0 right-0 w-64 h-64 bg-blue-500/5 rounded-full blur-3xl -mr-20 -mt-20 pointer-events-none" />
            <div className="flex items-start gap-4 relative z-10 mb-4">
              <div className="p-2.5 bg-blue-500/10 border border-blue-500/20 rounded-xl text-blue-400 shadow-sm flex-shrink-0">
                <Sparkles className="w-5 h-5" />
              </div>
              <div className="flex-1 min-w-0">
                <h3 className="text-[13px] uppercase tracking-wider font-bold text-slate-400">Dashboard Landscape Summary</h3>
              </div>
            </div>
            
            <div className="flex-grow min-h-0 relative z-10">
              {isLoadingSummary ? (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-slate-300 text-sm py-8">
                  <Loader2 className="w-6 h-6 animate-spin text-blue-500" />
                  <span className="animate-pulse text-center">Analyzing dashboard similarities and differences...</span>
                </div>
              ) : (
                <div className="text-sm text-slate-200 leading-relaxed whitespace-pre-wrap font-medium">
                  {aiSummary || "No summary available."}
                </div>
              )}
            </div>
          </div>
        )}
        
      </div>
      
      {isMaximized && (
        <div className="fixed inset-0 z-[200] bg-slate-950 p-4 flex flex-col animate-in fade-in duration-200">
          <KPIDashboardGraph 
            dashboards={dashboards} 
            height="calc(100vh - 80px)" 
            isMaximizedView={true} 
            onMinimize={() => setIsMaximized(false)} 
          />
        </div>
      )}
    </div>
  );
}