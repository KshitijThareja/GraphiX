"use client";
import React, { useState, useEffect } from "react";
import DocumentationTree, { DocTreeItem } from "./DocumentationTree";
import DocumentationViewer from "./DocumentationViewer";
import { Button } from "@/components/ui/button";
import { RefreshCw, Download } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";
import { useCallgraph } from "@/context/CallgraphContext";
import { Skeleton } from "@/components/ui/skeleton";

interface DocumentationPanelProps {
  repositoryId?: string;
  className?: string;
  selectedNodeId?: string;
  onNodeSelect?: (nodeId: string) => void;
}

export default function DocumentationPanel({
  repositoryId,
  className,
  selectedNodeId,
  onNodeSelect,
}: DocumentationPanelProps) {
  const [documentation, setDocumentation] = useState<DocTreeItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<DocTreeItem | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<string>("browse");
  const { toast } = useToast();
  const { repoUrl, callgraphData } = useCallgraph();

  const fetchDocumentation = async () => {
    if (!repositoryId && !repoUrl) {
      toast({
        title: "No repository selected",
        description: "Please select or analyze a repository first",
        variant: "destructive",
      });
      return;
    }

    setIsLoading(true);
    try {
      // Encode the repo URL if it's being used as the identifier
      const identifier = repositoryId || encodeURIComponent(repoUrl || '');
      console.log(`Fetching documentation for: ${identifier}`);

      // Use a relative URL to avoid cross-origin issues
      const response = await fetch(
        `/api/documentation/${identifier}`,
        {
          method: "GET",
          headers: {
            "Content-Type": "application/json",
          },
          cache: 'no-store',
        }
      );

      if (!response.ok) {
        const errorText = await response.text();
        console.error(`Documentation fetch error (${response.status}):`, errorText);
        throw new Error(errorText || `Error ${response.status}`);
      }

      const data = await response.json();
      console.log("Documentation fetch response:", data);
      
      if (data.documentation && Array.isArray(data.documentation) && data.documentation.length > 0) {
        console.log(`Received ${data.documentation.length} documentation items`);
        setDocumentation(data.documentation);
        
        // If a node is selected in the callgraph, try to find it in the documentation
        if (selectedNodeId) {
          findAndSelectDocumentationItem(data.documentation, selectedNodeId);
        }
      } else {
        console.warn("Documentation data is empty or not an array", data);
        // If documentation is not found, try to generate it
        if (callgraphData && !isLoading) {
          console.log("Documentation not found, trying to generate it...");
          setTimeout(() => generateDocumentation(), 500);
        }
      }
    } catch (error) {
      console.error("Failed to fetch documentation:", error);
      toast({
        title: "Failed to fetch documentation",
        description:
          error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      });
    } finally {
      setIsLoading(false);
    }
  };
  
  // Helper function to find a documentation item by node ID
  const findAndSelectDocumentationItem = (items: DocTreeItem[], nodeId: string) => {
    // Flatten the tree structure for easier searching
    const allItems = flattenDocumentationTree(items);
    
    // Find item with matching ID
    const item = allItems.find(item => item.id === nodeId);
    
    if (item) {
      handleSelectItem(item);
    }
  };
  
  const handleSelectItem = (item: DocTreeItem) => {
    setSelectedItem(item);
    setActiveTab("selected");
    
    // If onNodeSelect callback is provided and the item has an ID,
    // call it to highlight the corresponding node in the callgraph
    if (onNodeSelect && item.id) {
      onNodeSelect(item.id);
    }
  };
  
  // Helper function to flatten a tree structure
  const flattenDocumentationTree = (items: DocTreeItem[]): DocTreeItem[] => {
    let result: DocTreeItem[] = [];
    
    for (const item of items) {
      result.push(item);
      
      if (item.children && item.children.length > 0) {
        result = result.concat(flattenDocumentationTree(item.children));
      }
    }
    
    return result;
  };

  const generateDocumentation = async () => {
    if (!repositoryId && !repoUrl) {
      toast({
        title: "No repository selected",
        description: "Please select or analyze a repository first",
        variant: "destructive",
      });
      return;
    }

    setIsLoading(true);
    try {
      const identifier = repositoryId || encodeURIComponent(repoUrl || '');
      console.log(`Generating documentation for: ${identifier}`);
      
      // Use the API route we created
      const response = await fetch(
        `/api/documentation/${identifier}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            framework_hint: callgraphData?.metadata?.framework_analyzed_as || 'django',
            include_docstring_generation: true,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();
      toast({
        title: "Documentation generation started",
        description: "The documentation will be available soon",
      });
      
      // Poll for documentation updates
      const checkDocumentation = async () => {
        try {
          const pollResponse = await fetch(
            `/api/documentation/${identifier}`,
            {
              method: "GET",
              headers: {
                "Content-Type": "application/json",
              },
              cache: 'no-store',
            }
          );
          
          if (pollResponse.ok) {
            const pollData = await pollResponse.json();
            console.log("Documentation poll response:", pollData);
            
            if (pollData.documentation && pollData.documentation.length > 0) {
              setDocumentation(pollData.documentation);
              setIsLoading(false);
              toast({
                title: "Documentation ready",
                description: "Documentation has been generated successfully",
              });
            } else {
              // Continue polling
              setTimeout(checkDocumentation, 5000);
            }
          } else {
            // Continue polling even on error
            console.warn("Documentation poll error:", await pollResponse.text());
            setTimeout(checkDocumentation, 5000);
          }
        } catch (pollError) {
          console.error("Error polling for documentation:", pollError);
          setTimeout(checkDocumentation, 5000);
        }
      };
      
      setTimeout(checkDocumentation, 5000);
    } catch (error) {
      console.error("Failed to generate documentation:", error);
      toast({
        title: "Failed to generate documentation",
        description:
          error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      });
      setIsLoading(false);
    }
  };

  const downloadDocumentation = async (format = "markdown") => {
    if (!repositoryId && !repoUrl) {
      toast({
        title: "No repository selected",
        description: "Please select or analyze a repository first",
        variant: "destructive",
      });
      return;
    }

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/documentation/${
          repositoryId || repoUrl
        }/download?format=${format}`,
        {
          method: "GET",
          headers: {
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
        }
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      // Create a blob and download
      const blob = await response.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.style.display = "none";
      a.href = url;
      a.download = `documentation.${format}`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    } catch (error) {
      toast({
        title: "Failed to download documentation",
        description:
          error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      });
    }
  };

  useEffect(() => {
    console.log("DocumentationPanel useEffect triggered:", { 
      repositoryId, 
      repoUrl, 
      callgraphData: callgraphData ? 'present' : 'missing',
      hasNodes: callgraphData?.nodes?.length > 0
    });
    
    // Only fetch documentation if a repository is selected
    if (repositoryId || repoUrl) {
      console.log("Attempting to fetch documentation for", repositoryId || repoUrl);
      fetchDocumentation();
    } else {
      console.log("No repository ID or URL available yet");
    }
  }, [repositoryId, repoUrl, callgraphData]);
  
  // Listen for changes in selected node ID
  useEffect(() => {
    if (selectedNodeId && documentation.length > 0) {
      findAndSelectDocumentationItem(documentation, selectedNodeId);
    }
  }, [selectedNodeId, documentation]);
  
  // Generate documentation from callgraph data if available
  useEffect(() => {
    // Check if we have callgraph data but no documentation yet
    if (callgraphData && 
        callgraphData.nodes && 
        callgraphData.nodes.length > 0 && 
        documentation.length === 0 && 
        !isLoading) {
      console.log("Auto-generating documentation from callgraph data", {
        nodeCount: callgraphData.nodes.length,
        framework: callgraphData.metadata?.framework_analyzed_as || 'unknown'
      });
      // If we have callgraph data but no documentation, try to generate it
      generateDocumentation();
    }
  }, [callgraphData, documentation.length, isLoading]);

  return (
    <div className={`h-full grid grid-rows-[auto_1fr] gap-4 ${className}`}>
      <div className="flex flex-wrap gap-2 items-center justify-between p-2 bg-muted/30 rounded-md">
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={fetchDocumentation}
            disabled={isLoading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-1 ${isLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={generateDocumentation}
            disabled={isLoading}
          >
            Generate
          </Button>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => downloadDocumentation("markdown")}
            disabled={isLoading}
          >
            <Download className="h-4 w-4 mr-1" /> Markdown
          </Button>
          <Button
            size="sm"
            variant="outline"
            onClick={() => downloadDocumentation("html")}
            disabled={isLoading}
          >
            <Download className="h-4 w-4 mr-1" /> HTML
          </Button>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-[300px_1fr] gap-4">
          <Skeleton className="h-full w-full" />
          <Skeleton className="h-full w-full" />
        </div>
      ) : (
        <Tabs value={activeTab} onValueChange={setActiveTab} className="h-full">
          <TabsList className="mb-4">
            <TabsTrigger value="browse">Browse All</TabsTrigger>
            <TabsTrigger value="selected" disabled={!selectedItem}>Selected Element</TabsTrigger>
          </TabsList>
          
          <TabsContent value="browse" className="m-0 h-[calc(100%-40px)]">
            <div className="grid grid-cols-[300px_1fr] gap-4 h-full">
              <DocumentationTree
                documentation={documentation}
                onItemSelect={handleSelectItem}
                selectedItemId={selectedItem?.id}
              />
              <DocumentationViewer selectedItem={selectedItem} />
            </div>
          </TabsContent>
          
          <TabsContent value="selected" className="m-0 h-[calc(100%-40px)]">
            {selectedItem ? (
              <DocumentationViewer selectedItem={selectedItem} className="h-full" />
            ) : (
              <div className="flex items-center justify-center h-full">
                <p className="text-muted-foreground">No element selected. Select a node from the callgraph or documentation tree.</p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
