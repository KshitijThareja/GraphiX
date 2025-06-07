"use client";
import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import {
  CallgraphLink,
  DynamicAttributeProvider,
  VisualizationAttributes,
} from "@/lib/visualization/attributes";

// Extend the CallgraphNode type to include our visualization-specific properties
export interface CallgraphNode {
  id: string;
  name?: string;
  type: string;
  highlighted?: boolean;
  selected?: boolean;
  // Properties needed for D3 force simulation
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
  vx?: number;
  vy?: number;
  index?: number;
  // Additional metadata for visualization and analysis
  complexity?: number;
  file?: string;
  metadata?: {
    [key: string]: any;
  };
}
import { Button } from "./ui/button";
import { Info, Maximize, Minimize } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
interface CallgraphVisualizationProps {
  data: {
    nodes: CallgraphNode[];
    links: CallgraphLink[];
    metadata?: {
      framework_analyzed_as?: string;
      [key: string]: any;
    };
  };
  className?: string;
  onNodeClick?: (nodeId: string) => void;
}
export default function CallgraphVisualization({
  data,
  className,
  onNodeClick,
}: CallgraphVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const [selectedNode, setSelectedNode] = useState<CallgraphNode | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!svgRef.current || !data || !data.nodes || !data.links) return;
    const svg = d3.select(svgRef.current);
    const container = containerRef.current;
    if (!container) return;
    const width = container.clientWidth;
    const height = container.clientHeight;
    svg.selectAll("*").remove();
    d3.select("body").selectAll(".tooltip").remove();
    d3.select("body").selectAll(".callgraph-legend").remove();
    const framework = data.metadata?.framework_analyzed_as || "generic";
    const attributes: VisualizationAttributes =
      DynamicAttributeProvider.getAttributes(framework);
    const simulationNodes = data.nodes as (CallgraphNode &
      d3.SimulationNodeDatum)[];
    const nodeIds = new Set(simulationNodes.map((n) => n.id));
    const validSimulationLinks = (
      data.links as (CallgraphLink &
        d3.SimulationLinkDatum<CallgraphNode & d3.SimulationNodeDatum>)[]
    ).filter((link) => {
      const sourceId =
        typeof link.source === "object"
          ? (link.source as CallgraphNode).id
          : String(link.source);
      const targetId =
        typeof link.target === "object"
          ? (link.target as CallgraphNode).id
          : String(link.target);
      const sourceExists = nodeIds.has(sourceId);
      const targetExists = nodeIds.has(targetId);
      if (!sourceExists) {
        console.warn(
          `Source node with ID '${sourceId}' not found for link:`,
          link,
        );
      }
      if (!targetExists) {
        console.warn(
          `Target node with ID '${targetId}' not found for link:`,
          link,
        );
      }
      return sourceExists && targetExists;
    });
    const simulationLinks = validSimulationLinks;
    const simulation = d3
      .forceSimulation(simulationNodes)
      .force(
        "link",
        d3
          .forceLink(validSimulationLinks)
          .id((d_sim: d3.SimulationNodeDatum) => (d_sim as CallgraphNode).id)
          .distance(200), 
      )
      .force("charge", d3.forceManyBody().strength(-1000)) 
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collide",
        d3
          .forceCollide()
          .radius(
            (d_sim: d3.SimulationNodeDatum) =>
              attributes.nodeSize(d_sim as CallgraphNode) + 10,
          ),
      ); 
    const link = svg
      .append("g")
      .selectAll("line")
      .data(validSimulationLinks)
      .join("line")
      .attr("stroke", (d) => attributes.linkColor(d))
      .attr("stroke-opacity", 0.7)
      .attr("stroke-width", (d) => attributes.linkWidth(d))
      .attr("stroke-dasharray", (d) => attributes.linkDashArray(d) || null);
    const linkLabels = svg
      .append("g")
      .attr("class", "link-labels")
      .selectAll("text")
      .data(
        validSimulationLinks.filter(
          (d) =>
            d.metadata?.label ||
            ["MODEL_RELATION", "REDIRECT", "URL_ROUTE"].includes(
              d.type.toUpperCase(),
            ),
        ),
      )
      .enter()
      .append("text")
      .attr("font-size", "10px")
      .attr("text-anchor", "middle")
      .attr("dy", "-5")
      .attr("fill", "#666")
      .text((d) => d.metadata?.label || d.type.replace("_", " ").toLowerCase())
      .style("pointer-events", "none");
    const nodeGroup = svg
      .append("g")
      .selectAll("g")
      .data(simulationNodes)
      .join("g")
      .call(drag(simulation) as any)
      .on("click", (event, d) => {
        setSelectedNode(d);
        // Call the onNodeClick callback if provided
        if (onNodeClick && d.id) {
          onNodeClick(d.id);
        }
        event.stopPropagation();
      });
    const node = nodeGroup
      .selectAll("circle")
      .data(simulationNodes)
      .join("circle")
      .attr("r", (d) => attributes.nodeSize(d))
      .attr("fill", (d) => attributes.nodeColor(d))
      .attr("stroke", (d) => {
        if (d.highlighted) return "#ff3e00";
        if (d.selected) return "#4c9aff";
        return "transparent";
      })
      .attr("stroke-width", (d) => {
        if (d.highlighted || d.selected) return 3;
        return 0;
      })
      .style("cursor", "pointer")
      .call(drag(simulation) as any)
      .on("click", (event, d) => {
        event.stopPropagation();
        setSelectedNode(d);
        // Call the onNodeClick callback if provided
        if (onNodeClick && d.id) {
          onNodeClick(d.id);
        }
      });
    const labels = nodeGroup
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d) => attributes.nodeSize(d) + 15)
      .attr("font-size", "12px")
      .attr("fill", "#333")
      .text((d) => attributes.nodeLabel(d))
      .style("pointer-events", "none");
    const tooltip = d3
      .select("body")
      .append("div")
      .attr("class", "tooltip")
      .style("opacity", 0)
      .style("position", "absolute")
      .style("background-color", "#fff")
      .style("border", "1px solid #ddd")
      .style("border-radius", "8px")
      .style("padding", "10px")
      .style("pointer-events", "none")
      .style("font-size", "12px")
      .style("max-width", "350px")
      .style("box-shadow", "0 3px 10px rgba(0,0,0,0.2)")
      .style("z-index", "1000")
      .style("transition", "opacity 0.2s");
    nodeGroup
      .on(
        "mouseover.tooltip",
        function (event, d_node: CallgraphNode & d3.SimulationNodeDatum) {
          d3.select(this)
            .select("circle")
            .attr("stroke-width", 3)
            .attr("stroke", "#555");
          let tooltipContent = `<strong>ID:</strong> ${d_node.id}<br/><strong>Type:</strong> ${d_node.type}`;
          if (d_node.metadata) {
            tooltipContent += `<br/>---<br/><strong>Metadata:</strong><div style="max-height: 150px; overflow-y: auto;">`;
            for (const key in d_node.metadata) {
              let value = d_node.metadata[key];
              if (typeof value === "object") {
                value = JSON.stringify(value);
              }
              if (value && value.toString().length > 100) {
                value = value.toString().substring(0, 97) + "...";
              }
              tooltipContent += `<br/><em>${key}:</em> ${value}`;
            }
            tooltipContent += `</div>`;
          }
          if (d_node.type === "template") {
            const templatePath = d_node.id.replace("template:", "");
            const parts = templatePath.split("/");
            const app = parts.length > 1 ? parts[0] : "Unknown";
            const filename = parts[parts.length - 1];
            tooltipContent = `<strong>Template</strong><hr/>
            <strong>Path:</strong> ${templatePath}<br/>
            <strong>App:</strong> ${app}<br/>
            <strong>File:</strong> ${filename}<br/>`;
            if (d_node.metadata?.context_variables?.length) {
              tooltipContent += `<strong>Context:</strong> ${d_node.metadata.context_variables.join(", ")}<br/>`;
            }
          } else if (d_node.type === "model") {
            tooltipContent = `<strong>Model: ${d_node.name || d_node.id}</strong><hr/>
            <strong>App:</strong> ${d_node.metadata?.app_label || "N/A"}<br/>`;
            if (d_node.metadata?.fields?.length) {
              tooltipContent += `<strong>Fields:</strong> ${d_node.metadata.fields.join(", ")}<br/>`;
            }
          } else if (
            d_node.type === "view" ||
            d_node.type === "function" ||
            d_node.type === "class"
          ) {
            tooltipContent = `<strong>${d_node.type.charAt(0).toUpperCase() + d_node.type.slice(1)}: ${d_node.name || d_node.id}</strong><hr/>
            <strong>Module:</strong> ${d_node.metadata?.module || "N/A"}<br/>`;
            if (d_node.metadata?.args)
              tooltipContent += `<strong>Args:</strong> ${d_node.metadata.args.join(", ")}<br/>`;
            if (d_node.metadata?.docstring)
              tooltipContent += `<strong>Doc:</strong> ${d_node.metadata.docstring.substring(0, 100)}...<br/>`;
          }
          tooltip.transition().duration(200).style("opacity", 0.95);
          tooltip
            .html(tooltipContent)
            .style("left", event.pageX + 15 + "px")
            .style("top", event.pageY - 28 + "px");
        },
      )
      .on(
        "mouseout.tooltip",
        function (event, d_node: CallgraphNode & d3.SimulationNodeDatum) {
          d3.select(this)
            .select("circle")
            .attr("stroke-width", 1.5)
            .attr("stroke", "#fff");
          tooltip.transition().duration(500).style("opacity", 0);
        },
      );
    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      linkLabels
        .attr("x", (d: any) => (d.source.x + d.target.x) / 2)
        .attr("y", (d: any) => (d.source.y + d.target.y) / 2);
      nodeGroup.attr("transform", (d) => `translate(${d.x},${d.y})`);
    });
    function drag(
      simulation: d3.Simulation<
        CallgraphNode & d3.SimulationNodeDatum,
        undefined
      >,
    ) {
      function dragstarted(event: any, d: any) {
        if (!event.active) simulation.alphaTarget(0.3).restart();
        d.fx = d.x;
        d.fy = d.y;
      }
      function dragged(event: any, d: any) {
        d.fx = event.x;
        d.fy = event.y;
      }
      function dragended(event: any, d: any) {
        if (!event.active) simulation.alphaTarget(0);
        d.fx = null;
        d.fy = null;
      }
      return d3
        .drag()
        .on("start", dragstarted)
        .on("drag", dragged)
        .on("end", dragended);
    }
    const zoom = d3
      .zoom()
      .scaleExtent([0.1, 8])
      .on("zoom", (event) => {
        svg.selectAll("g").attr("transform", event.transform);
      });
    svg.call(zoom as any);
    svg.on("click", () => setSelectedNode(null));
    const handleResize = () => {
      if (!container) return;
      const newWidth = container.clientWidth;
      const newHeight = container.clientHeight;
      svg.attr("width", newWidth).attr("height", newHeight);
      simulation.force("center", d3.forceCenter(newWidth / 2, newHeight / 2));
      simulation.alpha(0.3).restart();
    };
    window.addEventListener("resize", handleResize);
    return () => {
      simulation.stop();
      window.removeEventListener("resize", handleResize);
    };
  }, [data, selectedNode]);
  
  // Effect to handle highlighted nodes from chat interaction
  useEffect(() => {
    if (!svgRef.current) return;
    
    // Update node highlighting
    const svg = d3.select(svgRef.current);
    svg.selectAll("circle")
      .attr("stroke", (d: any) => d.highlighted ? "#ff3e00" : "transparent")
      .attr("stroke-width", (d: any) => d.highlighted ? 3 : 0);
      
    // If a node is highlighted, scroll to it
    const highlightedNode = data?.nodes.find((node) => node.highlighted);
    if (highlightedNode && highlightedNode.x && highlightedNode.y) {
      // Zoom to the highlighted node
      const container = containerRef.current;
      if (container) {
        const width = container.clientWidth;
        const height = container.clientHeight;
        
        const zoom = d3.zoom();
        const transform = d3.zoomIdentity
          .translate(width/2 - highlightedNode.x, height/2 - highlightedNode.y)
          .scale(1.5);
          
        svg.transition().duration(750).call(zoom.transform as any, transform);
      }
    }
  }, [data]);
  const toggleFullscreen = () => {
    if (!containerRef.current) return;
    if (!isFullscreen) {
      containerRef.current.requestFullscreen();
    } else {
      document.exitFullscreen();
    }
    setIsFullscreen(!isFullscreen);
  };
  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <svg
        ref={svgRef}
        className="w-full h-full rounded-lg border bg-background"
      />
      <div className="absolute top-4 right-4 flex gap-2">
        <TooltipProvider>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                onClick={toggleFullscreen}
                className="bg-background/80 backdrop-blur-sm"
              >
                {isFullscreen ? (
                  <Minimize className="h-4 w-4" />
                ) : (
                  <Maximize className="h-4 w-4" />
                )}
              </Button>
            </TooltipTrigger>
            <TooltipContent>
              {isFullscreen ? "Exit fullscreen" : "Enter fullscreen"}
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      {selectedNode && (
        <div className="absolute bottom-4 left-4 right-4 bg-background/80 backdrop-blur-sm p-4 rounded-lg border shadow-lg max-h-[200px] overflow-y-auto">
          <div className="flex justify-between items-start mb-2">
            <h3 className="font-bold text-lg">
              {selectedNode.id.split(".").pop()}
            </h3>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setSelectedNode(null)}
            >
              <span className="sr-only">Close</span>×
            </Button>
          </div>
          <div className="grid grid-cols-2 gap-2 text-sm">
            <div>
              <p className="text-muted-foreground">Type</p>
              <p className="capitalize">{selectedNode.type}</p>
            </div>
            <div>
              <p className="text-muted-foreground">Complexity</p>
              <p>{selectedNode.complexity}</p>
            </div>
            <div className="col-span-2">
              <p className="text-muted-foreground">File</p>
              <p className="truncate">{selectedNode.file}</p>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
