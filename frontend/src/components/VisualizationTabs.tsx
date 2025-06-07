"use client";
import React, { useState, useEffect } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import DocumentationPanel from "./documentation/DocumentationPanel";
import ChatInterface from "./chat/ChatInterface";
import { cn } from "@/lib/utils";
// Import CallgraphVisualization and required types
import CallgraphVisualization, { CallgraphNode } from "./callgraph-visualization";
import { CallgraphLink } from "@/lib/visualization/attributes";

interface VisualizationTabsProps {
  data: {
    nodes: any[];
    links: any[];
    metadata?: {
      framework_analyzed_as?: string;
      [key: string]: any;
    };
  };
  repositoryId?: string;
  className?: string;
}

export default function VisualizationTabs({
  data,
  repositoryId,
  className,
}: VisualizationTabsProps) {
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string>("callgraph");

  // Function to handle node highlighting from the chat
  const handleHighlightNode = (nodeId: string) => {
    setHighlightedNodeId(nodeId);
    
    // Ensure the callgraph tab is active when highlighting a node
    setActiveTab("callgraph");
  };
  
  // Function to handle node selection from the callgraph
  const handleNodeSelect = (nodeId: string) => {
    setSelectedNodeId(nodeId);
    
    // Switch to the documentation tab when a node is selected in the callgraph
    setActiveTab("documentation");
  };
  
  // Function to handle node selection from the documentation panel
  const handleDocNodeSelect = (nodeId: string) => {
    setHighlightedNodeId(nodeId);
    setActiveTab("callgraph");
  };

  // Enhance the callgraph data with highlighting information
  const enhancedData = {
    ...data,
    nodes: data.nodes.map((node) => ({
      ...node,
      highlighted: node.id === highlightedNodeId,
      selected: node.id === selectedNodeId,
    })) as CallgraphNode[],
  };

  return (
    <Tabs 
      value={activeTab} 
      onValueChange={setActiveTab} 
      className={cn("flex flex-col h-full", className)}
    >
      <TabsList className="mb-4">
        <TabsTrigger value="callgraph">Callgraph</TabsTrigger>
        <TabsTrigger value="documentation">Documentation</TabsTrigger>
        <TabsTrigger value="chat">Chat</TabsTrigger>
      </TabsList>
      
      <TabsContent value="callgraph" className="flex-1 m-0 h-full">
        <CallgraphVisualization 
          data={enhancedData} 
          className="h-full"
          onNodeClick={handleNodeSelect}
        />
      </TabsContent>
      
      <TabsContent value="documentation" className="flex-1 m-0 h-full">
        <DocumentationPanel 
          repositoryId={repositoryId}
          className="h-full"
          selectedNodeId={selectedNodeId || undefined}
          onNodeSelect={handleDocNodeSelect}
        />
      </TabsContent>
      
      <TabsContent value="chat" className="flex-1 m-0 h-full">
        <ChatInterface 
          repositoryId={repositoryId}
          onHighlightNode={handleHighlightNode}
          className="h-full"
        />
      </TabsContent>
    </Tabs>
  );
}
