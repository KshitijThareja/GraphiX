"use client";
import React, { useState, useEffect } from "react";
import DocumentationTree, { DocTreeItem } from "./DocumentationTree";
import DocumentationViewer from "./DocumentationViewer";
import { Button } from "@/components/ui/button";
import { RefreshCw, Download } from "lucide-react";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/components/ui/use-toast";
import { useCallgraph } from "@/context/CallgraphContext";

interface DocumentationPanelProps {
  repositoryId?: string;
  className?: string;
}

export default function DocumentationPanel({
  repositoryId,
  className,
}: DocumentationPanelProps) {
  const [documentation, setDocumentation] = useState<DocTreeItem[]>([]);
  const [selectedItem, setSelectedItem] = useState<DocTreeItem | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const { toast } = useToast();
  const { repoUrl } = useCallgraph();

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
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          cache: 'no-store',
          next: { revalidate: 0 },
        }
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();
      setDocumentation(data.documentation || []);
    } catch (error) {
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
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/documentation/generate`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          body: JSON.stringify({
            repository_id: repositoryId || repoUrl,
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
        const pollResponse = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/documentation/${
            repositoryId || repoUrl
          }`,
          {
            method: "GET",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${localStorage.getItem("token")}`,
            },
          }
        );
        
        if (pollResponse.ok) {
          const pollData = await pollResponse.json();
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
        }
      };
      
      setTimeout(checkDocumentation, 5000);
    } catch (error) {
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
    if (repositoryId || repoUrl) {
      fetchDocumentation();
    }
  }, [repositoryId, repoUrl]);

  return (
    <div className={`flex flex-col h-full ${className}`}>
      <div className="flex justify-between items-center mb-4">
        <h2 className="text-xl font-bold">Documentation</h2>
        <div className="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={fetchDocumentation}
            disabled={isLoading}
          >
            <RefreshCw
              className={`h-4 w-4 mr-2 ${isLoading ? "animate-spin" : ""}`}
            />
            Refresh
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={generateDocumentation}
            disabled={isLoading}
          >
            {isLoading ? (
              <RefreshCw className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              "Generate"
            )}
          </Button>
          <Button
            variant="outline"
            size="sm"
            onClick={() => downloadDocumentation("markdown")}
            disabled={isLoading || documentation.length === 0}
          >
            <Download className="h-4 w-4 mr-2" />
            Download
          </Button>
        </div>
      </div>
      <div className="flex flex-1 gap-4 h-full">
        <div className="w-1/3">
          <DocumentationTree
            documentation={documentation}
            onItemSelect={setSelectedItem}
            selectedItemId={selectedItem?.id}
          />
        </div>
        <div className="w-2/3">
          <DocumentationViewer selectedItem={selectedItem} />
        </div>
      </div>
    </div>
  );
}
