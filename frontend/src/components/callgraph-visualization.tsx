"use client"

import { useEffect, useRef, useState } from "react"
import * as d3 from "d3"
import { CallgraphNode, CallgraphLink } from "@/lib/types"
import { Button } from "./ui/button"
import { Info, Maximize, Minimize } from "lucide-react"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"

interface CallgraphVisualizationProps {
  data: {
    nodes: CallgraphNode[]
    links: CallgraphLink[]
  }
  className?: string
}

export default function CallgraphVisualization({ data, className }: CallgraphVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)
  const [selectedNode, setSelectedNode] = useState<CallgraphNode | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!svgRef.current || !data) return

    const svg = d3.select(svgRef.current)
    const container = containerRef.current
    if (!container) return

    const width = container.clientWidth
    const height = container.clientHeight

    svg.selectAll("*").remove()

    const simulation = d3
      .forceSimulation(data.nodes as any)
      .force(
        "link",
        d3
          .forceLink(data.links as any)
          .id((d: any) => d.id)
          .distance(120) // Increased distance for better spacing
      )
      .force("charge", d3.forceManyBody().strength(-400)) // Increased repulsion to reduce overlap
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius(30)) // Increased collision radius to prevent overlap

    const color = d3.scaleOrdinal(d3.schemeCategory10)
    const sizeScale = d3
      .scaleLinear()
      .domain([0, d3.max(data.nodes, (d) => d.complexity) || 10])
      .range([12, 25]) // Increased min radius for better visibility

    const link = svg
      .append("g")
      .attr("stroke", "#999")
      .attr("stroke-opacity", 0.6)
      .selectAll("line")
      .data(data.links)
      .join("line")
      .attr("stroke-width", 1)

    const nodeGroup = svg
      .append("g")
      .selectAll("g")
      .data(data.nodes)
      .join("g")
      .call(drag(simulation) as any)
      .on("click", (event, d) => {
        setSelectedNode(d)
        event.stopPropagation()
      })
      .on("mouseover", function (event, d) {
        d3.select(this).select("circle").attr("stroke-width", 3) // Highlight on hover
      })
      .on("mouseout", function (event, d) {
        d3.select(this).select("circle").attr("stroke-width", 1.5) // Remove highlight
      })

    const node = nodeGroup
      .append("circle")
      .attr("r", (d: any) => sizeScale(d.complexity))
      .attr("fill", (d: any) => color(d.group.toString()))
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5)

    const labels = nodeGroup
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", (d: any) => sizeScale(d.complexity) + 15) // Offset below the node
      .attr("font-size", "12px") // Increased font size for readability
      .attr("fill", "#333")
      .text((d: any) => {
        const parts = d.id.split(".")
        const name = parts[parts.length - 1]
        // Truncate long names (e.g., > 15 characters) with ellipsis
        return name.length > 15 ? name.substring(0, 12) + "..." : name
      })

    // Add tooltips with full information
    nodeGroup
      .append("title")
      .text((d: any) => 
        `${d.id}\nType: ${d.type}\nComplexity: ${d.complexity}\nFile: ${d.file}`
      )

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y)

      nodeGroup.attr("transform", (d: any) => `translate(${d.x},${d.y})`)
    })

    const zoom = d3
      .zoom()
      .scaleExtent([0.1, 8])
      .on("zoom", (event) => {
        svg.selectAll("g").attr("transform", event.transform)
      })

    svg.call(zoom as any)

    svg.on("click", () => setSelectedNode(null))

    const handleResize = () => {
      if (!container) return
      const newWidth = container.clientWidth
      const newHeight = container.clientHeight
      
      svg.attr("width", newWidth).attr("height", newHeight)
      simulation.force("center", d3.forceCenter(newWidth / 2, newHeight / 2))
      simulation.alpha(0.3).restart()
    }

    window.addEventListener("resize", handleResize)

    return () => {
      simulation.stop()
      window.removeEventListener("resize", handleResize)
    }
  }, [data, selectedNode])

  function drag(simulation: any) {
    function dragstarted(event: any, d: any) {
      if (!event.active) simulation.alphaTarget(0.3).restart()
      d.fx = d.x
      d.fy = d.y
    }

    function dragged(event: any, d: any) {
      d.fx = event.x
      d.fy = event.y
    }

    function dragended(event: any, d: any) {
      if (!event.active) simulation.alphaTarget(0)
      d.fx = null
      d.fy = null
    }

    return d3.drag().on("start", dragstarted).on("drag", dragged).on("end", dragended)
  }

  const toggleFullscreen = () => {
    if (!containerRef.current) return
    
    if (!isFullscreen) {
      containerRef.current.requestFullscreen()
    } else {
      document.exitFullscreen()
    }
    
    setIsFullscreen(!isFullscreen)
  }

  return (
    <div className={`relative ${className}`} ref={containerRef}>
      <svg ref={svgRef} className="w-full h-full rounded-lg border bg-background" />
      
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
                {isFullscreen ? <Minimize className="h-4 w-4" /> : <Maximize className="h-4 w-4" />}
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
            <h3 className="font-bold text-lg">{selectedNode.id.split(".").pop()}</h3>
            <Button
              variant="ghost"
              size="icon"
              className="h-6 w-6"
              onClick={() => setSelectedNode(null)}
            >
              <span className="sr-only">Close</span>
              ×
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
  )
}