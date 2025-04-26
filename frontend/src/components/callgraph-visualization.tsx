"use client"

import { useEffect, useRef } from "react"
import * as d3 from "d3"

interface Node {
  id: string
  group: number
  type: string
  complexity: number
}

interface Link {
  source: string
  target: string
  value: number
}

interface CallgraphData {
  nodes: Node[]
  links: Link[]
}

interface CallgraphVisualizationProps {
  data: CallgraphData
}

export default function CallgraphVisualization({ data }: CallgraphVisualizationProps) {
  const svgRef = useRef<SVGSVGElement>(null)

  useEffect(() => {
    if (!svgRef.current || !data) return

    const svg = d3.select(svgRef.current)
    const width = svgRef.current.clientWidth
    const height = svgRef.current.clientHeight

    // Clear previous visualization
    svg.selectAll("*").remove()

    // Create a force simulation
    const simulation = d3
      .forceSimulation(data.nodes as any)
      .force(
        "link",
        d3
          .forceLink(data.links as any)
          .id((d: any) => d.id)
          .distance(100),
      )
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius(50))

    // Create a color scale for node groups
    const color = d3.scaleOrdinal(d3.schemeCategory10)

    // Create a scale for node size based on complexity
    const sizeScale = d3
      .scaleLinear()
      .domain([0, d3.max(data.nodes, (d) => d.complexity) || 10])
      .range([5, 15])

    // Create links
    const link = svg
      .append("g")
      .attr("stroke", "#999")
      .attr("stroke-opacity", 0.6)
      .selectAll("line")
      .data(data.links)
      .join("line")
      .attr("stroke-width", (d: any) => Math.sqrt(d.value))

    // Create nodes
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

    // Add node labels
    const labels = svg
      .append("g")
      .selectAll("text")
      .data(data.nodes)
      .join("text")
      .attr("text-anchor", "middle")
      .attr("dy", ".35em")
      .attr("font-size", "10px")
      .text((d: any) => d.id)
      .attr("pointer-events", "none")

    // Add tooltips
    node.append("title").text((d: any) => `${d.id}\nType: ${d.type}\nComplexity: ${d.complexity}`)

    // Update positions on simulation tick
    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y)

      node.attr("cx", (d: any) => d.x).attr("cy", (d: any) => d.y)

      labels.attr("x", (d: any) => d.x).attr("y", (d: any) => d.y)
    })

    // Add zoom functionality
    const zoom = d3
      .zoom()
      .scaleExtent([0.1, 10])
      .on("zoom", (event) => {
        svg.selectAll("g").attr("transform", event.transform)
      })

    svg.call(zoom as any)

    // Drag function for nodes
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

    // Cleanup
    return () => {
      simulation.stop()
    }
  }, [data])

  return <svg ref={svgRef} className="w-full h-full border rounded-lg bg-background"></svg>
}
