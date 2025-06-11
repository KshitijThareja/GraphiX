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
          .distance(100)
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius(60))

    const color = d3.scaleOrdinal(d3.schemeCategory10)
    const sizeScale = d3
      .scaleLinear()
      .domain([0, d3.max(data.nodes, (d) => d.complexity) || 10])
      .range([5, 20])

    const link = svg
      .append("g")
      .attr("stroke", "#999")
      .attr("stroke-opacity", 0.6)
      .selectAll("line")
      .data(data.links)
      .join("line")
      .attr("stroke-width", 1)

    const node = svg
      .append("g")
      .attr("stroke", "#fff")
      .attr("stroke-width", 1.5)
      .selectAll("circle")
      .data(data.nodes)
      .join("circle")
      .attr("r", (d: any) => sizeScale(d.complexity))
      .attr("fill", (d: any) => color(d.group.toString()))
      .call(drag(simulation) as any)
      .on("click", (event, d) => {
        setSelectedNode(d)
        event.stopPropagation()
      })

    const labels = svg
      .append("g")
      .selectAll("text")
      .data(data.nodes)
      .join("text")
      .attr("text-anchor", "middle")
      .attr("dy", ".35em")
      .attr("font-size", "10px")
      .text((d: any) => {
        const parts = d.id.split(".")
        return parts[parts.length - 1]
      })
      .attr("pointer-events", "none")

    node.append("title").text((d: any) => 
      `${d.id}\nType: ${d.type}\nComplexity: ${d.complexity}\nFile: ${d.file}`
    )

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y)

      node.attr("cx", (d: any) => d.x).attr("cy", (d: any) => d.y)

      labels.attr("x", (d: any) => d.x).attr("y", (d: any) => d.y)
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
  }, [data])

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