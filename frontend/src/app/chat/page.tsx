"use client";
import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { useCallgraph } from "@/context/CallgraphContext";
import ChatInterface from "@/components/chat/ChatInterface";
import { useRouter } from "next/navigation";
import { Button } from "@/components/ui/button";
import { ArrowLeft } from "lucide-react";

export default function ChatPage() {
  const { repoUrl, callgraphData, documentation } = useCallgraph();
  const router = useRouter();
  const [highlightedNodeId, setHighlightedNodeId] = useState<string | null>(null);

  // If no repository data, show a message
  if (!repoUrl || !callgraphData) {
    return (
      <div className="container py-12">
        <h1 className="text-3xl font-bold mb-6">Chat with GraphiX AI</h1>
        <Card>
          <CardHeader>
            <CardTitle>No Repository Selected</CardTitle>
            <CardDescription>
              You need to analyze a repository first to chat about it
            </CardDescription>
          </CardHeader>
          <CardContent className="flex justify-center p-6">
            <Button onClick={() => router.push("/visualize")}>
              Go to Visualization Page
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const handleHighlightNode = (nodeId: string) => {
    setHighlightedNodeId(nodeId);
    // In a real implementation, you might want to communicate with the visualization component
    console.log(`Node highlighted: ${nodeId}`);
  };

  return (
    <div className="container py-12">
      <div className="flex items-center gap-4 mb-6">
        <Button variant="outline" size="icon" onClick={() => router.push("/visualize")}>
          <ArrowLeft className="h-4 w-4" />
        </Button>
        <h1 className="text-3xl font-bold">Chat with GraphiX AI</h1>
      </div>
      
      <Card className="mb-4">
        <CardHeader className="pb-2">
          <CardTitle className="text-lg">Repository: {repoUrl}</CardTitle>
          <CardDescription>
            Ask questions about the codebase using the callgraph and documentation
          </CardDescription>
        </CardHeader>
      </Card>
      
      <div className="h-[calc(100vh-250px)]">
        <ChatInterface 
          repositoryId={repoUrl} 
          onHighlightNode={handleHighlightNode} 
        />
      </div>
    </div>
  );
}
