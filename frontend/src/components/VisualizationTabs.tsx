"use client";
import React, { useState } from "react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import CallgraphVisualization from "./callgraph-visualization";
import DocumentationPanel from "./documentation/DocumentationPanel";
import ChatInterface from "./chat/ChatInterface";
import { cn } from "@/lib/utils";

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

  // Function to handle node highlighting from the chat
  const handleHighlightNode = (nodeId: string) => {
    setHighlightedNodeId(nodeId);
    
    // Ensure the callgraph tab is active when highlighting a node
    const callgraphTab = document.querySelector('[data-state="inactive"][data-value="callgraph"]') as HTMLElement;
    if (callgraphTab) {
      callgraphTab.click();
    }
  };

  // Enhance the callgraph data with highlighting information
  const enhancedData = {
    ...data,
    nodes: data.nodes.map((node) => ({
      ...node,
      highlighted: node.id === highlightedNodeId,
    })),
  };

  return (
    <Tabs defaultValue="callgraph" className={cn("flex flex-col h-full", className)}>
      <TabsList className="mb-4">
        <TabsTrigger value="callgraph">Callgraph</TabsTrigger>
        <TabsTrigger value="documentation">Documentation</TabsTrigger>
        <TabsTrigger value="chat">Chat</TabsTrigger>
      </TabsList>
      
      <TabsContent value="callgraph" className="flex-1 m-0 h-full">
        <CallgraphVisualization 
          data={enhancedData} 
          className="h-full"
        />
      </TabsContent>
      
      <TabsContent value="documentation" className="flex-1 m-0 h-full">
        <DocumentationPanel 
          repositoryId={repositoryId}
          className="h-full"
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
