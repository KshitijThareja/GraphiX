"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { GithubIcon } from "lucide-react"; 
import { CallgraphNode } from "@/lib/visualization/attributes"; 
import VisualizationTabs from "@/components/VisualizationTabs";
import { useToast } from "@/components/ui/use-toast";
import { useAuth } from "@/providers/auth-provider";
import { Skeleton } from "@/components/ui/skeleton";
import { useCallgraph } from "@/context/CallgraphContext";
export default function VisualizePage() {
  const {
    repoUrl,
    setRepoUrl,
    callgraphData,
    setCallgraphData,
    metrics,
    setMetrics,
    clearCallgraphData,
  } = useCallgraph();
  const [isLoading, setIsLoading] = useState(false);
  const [useResearchGrade, setUseResearchGrade] = useState(false);
  const [frameworkHint, setFrameworkHint] = useState("django");
  const [contextSensitivity, setContextSensitivity] = useState<number>(3);
  const [chatQuery, setChatQuery] = useState("");
  const [chatResponse, setChatResponse] = useState("");
  const [dataset, setDataset] = useState<any[]>([]);
  const [benchmarkResult, setBenchmarkResult] = useState<number | null>(null);
  const { toast } = useToast();
  const { isAuthenticated } = useAuth();
  const MAX_RETRIES = 3;
  const REQUEST_TIMEOUT = 200000;
  const RETRY_DELAY = 5000;
  // Check if analysis is already in progress or complete
  const checkExistingResults = async () => {
    if (!repoUrl) return null;
    
    try {
      // Get the auth token
      const token = localStorage.getItem('authToken');
      
      // Check if there are existing results for this repository
      const checkResponse = await fetch(`/api/analysis/callgraph/status?repo_url=${encodeURIComponent(repoUrl)}`, {
        headers: {
          "Content-Type": "application/json",
          ...(token ? { "Authorization": `Bearer ${token}` } : {})
        },
        cache: 'no-store',
      });
      
      if (checkResponse.ok) {
        const status = await checkResponse.json();
        console.log("Status check result:", status);
        return status;
      }
    } catch (error) {
      console.error("Error checking analysis status:", error);
    }
    return null;
  };
  
  // Poll for analysis results
  const pollForResults = async () => {
    setIsLoading(true);
    let attempts = 0;
    const maxAttempts = 20; // Maximum 20 attempts with 10 second intervals = ~3.3 minutes of polling
    
    const poll = async () => {
      if (attempts >= maxAttempts) {
        toast({
          title: "Polling timeout",
          description: "Couldn't retrieve analysis results after multiple attempts. The analysis may still be running. Try again later.",
          variant: "destructive",
        });
        setIsLoading(false);
        return;
      }
      
      attempts++;
      const status = await checkExistingResults();
      
      if (status && status.status === 'completed' && status.data) {
        // Success! We have results
        const normalizedData = {
          nodes: status.data.nodes || [],
          links: status.data.links || [],
          metadata: status.data.metadata || {}
        };
        
        console.log("Retrieved callgraph data via polling:", normalizedData);
        setCallgraphData(normalizedData);
        
        toast({
          title: "Analysis complete",
          description: "Successfully retrieved analysis results for " + repoUrl,
        });
        
        setIsLoading(false);
      } else if (status && status.status === 'error') {
        // Error occurred during analysis
        toast({
          title: "Analysis failed",
          description: status.message || "An unknown error occurred during analysis",
          variant: "destructive",
        });
        setIsLoading(false);
      } else {
        // Still processing or no status - continue polling
        console.log(`Polling attempt ${attempts}/${maxAttempts}. Status: ${status ? status.status : 'unknown'}`);
        setTimeout(poll, 10000); // Poll every 10 seconds
      }
    };
    
    // Start polling
    await poll();
  };

  const handleAnalyze = async (retryCount = 0) => {
    if (!repoUrl) {
      toast({
        title: "Repository URL required",
        description: "Please enter a valid GitHub repository URL",
        variant: "destructive",
      });
      return;
    }
    
    // First check if analysis is already in progress or complete
    setIsLoading(true);
    const existingStatus = await checkExistingResults();
    
    if (existingStatus) {
      console.log("Found existing analysis status:", existingStatus);
      
      if (existingStatus.status === 'completed' && existingStatus.data) {
        // We already have results - use them
        const normalizedData = {
          nodes: existingStatus.data.nodes || [],
          links: existingStatus.data.links || [],
          metadata: existingStatus.data.metadata || {}
        };
        
        console.log("Using existing callgraph data:", normalizedData);
        setCallgraphData(normalizedData);
        
        toast({
          title: "Analysis already complete",
          description: "Using existing analysis results for " + repoUrl,
        });
        
        setIsLoading(false);
        return;
      } else if (existingStatus.status === 'processing') {
        // Analysis is still in progress - start polling
        toast({
          title: "Analysis in progress",
          description: "Analysis is already running. Checking for results...",
        });
        
        pollForResults();
        return;
      }
    }
    
    // No existing analysis or it failed - start a new one
    clearCallgraphData();
    try {
      const controller = new AbortController();
      let timeoutId: NodeJS.Timeout | null = null;
      
      // Only set timeout on client side
      if (typeof window !== 'undefined') {
        timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
      }
      
      // Safe localStorage access for client-side only
      const token = typeof window !== 'undefined' ? localStorage.getItem("token") : null;
      
      const response = await fetch(`/api/analysis/callgraph`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
          repo_url: repoUrl,
          research_grade: useResearchGrade,
          framework_hint: frameworkHint,
          context_sensitivity: contextSensitivity, 
        }),
        signal: controller.signal,
      });
      
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
      
      let data;
      if (!response.ok) {
        const errorText = await response.text();
        console.error("API error:", errorText);
        throw new Error(errorText);
      }
      
      try {
        data = await response.json();
        console.log("Callgraph data:", data);
      } catch (jsonError) {
        console.error("JSON parsing error:", jsonError);
        throw new Error("Failed to parse response from server");
      }
      if (
        data.metadata?.fallback_used &&
        (!data.nodes?.length || !data.links?.length)
      ) {
        console.warn("Received fallback data without complete call graph");
        setCallgraphData({
          ...data,
          metadata: {
            ...data.metadata,
            error:
              "Analysis completed but could not generate a complete call graph",
          },
        });
        toast({
          title: "Analysis Incomplete",
          description:
            "Could not generate a complete call graph. Try again or use a different repository.",
          variant: "destructive",
        });
        setIsLoading(false);
        return;
      }
      // Normalize the data structure to ensure it's in the correct format for our components
      // Some API responses include data directly, others wrap it in a data property
      const normalizedData = {
        nodes: data.nodes || data.data?.nodes || [],
        links: data.links || data.data?.links || [],
        metadata: data.metadata || data.data?.metadata || {}
      };
      
      console.log("Normalized callgraph data:", normalizedData);
      setCallgraphData(normalizedData);
      
      const apiResponse = data; 
      const newMetrics = {
        functionCount: normalizedData.nodes.length || 0,
        dependencyCount: normalizedData.links.length || 0,
        avgComplexity: normalizedData.metadata?.metrics?.avg_complexity || "N/A",
        mostComplexFunction:
          normalizedData.metadata?.metrics?.most_complex_function || null,
        
        complexity: normalizedData.metadata?.metrics?.complexity || "N/A",
        cohesion: normalizedData.metadata?.metrics?.cohesion || "N/A",
        coupling: normalizedData.metadata?.metrics?.coupling || "N/A",
      };
      setMetrics(newMetrics);
      toast({
        title: "Repository analyzed",
        description:
          `Successfully analyzed ${repoUrl}` +
          (useResearchGrade ? " with research-grade analysis" : ""),
      });
    } catch (error: any) {
      console.error("Analysis error:", error);
      if (error.name === "AbortError") {
        toast({
          title: "Request timed out",
          description:
            "The analysis is taking too long. This may be due to a large codebase. Please try again or analyze a smaller repository.",
          variant: "destructive",
        });
      } else if (error.code === "ECONNRESET" && retryCount < MAX_RETRIES) {
        toast({
          title: "Connection reset",
          description: `Retrying analysis (${retryCount + 1}/${MAX_RETRIES})...`,
          variant: "default",
        });
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY));
        return handleAnalyze(retryCount + 1);
      } else {
        toast({
          title: "Analysis failed",
          description:
            error.message || "Unknown error occurred. Please try again.",
          variant: "destructive",
        });
      }
    } finally {
      setIsLoading(false);
    }
  };
  const handleChat = async () => {
    if (!chatQuery) {
      toast({
        title: "Query required",
        description: "Please enter a chat query",
        variant: "destructive",
      });
      return;
    }
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/analysis/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          body: JSON.stringify({
            query: chatQuery,
            repo_url: repoUrl,
          }),
          signal: controller.signal,
        },
      );
      clearTimeout(timeoutId);
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const data = await response.json();
      setChatResponse(data.response);
    } catch (error: any) {
      if (error.name === "AbortError") {
        toast({
          title: "Request timed out",
          description: "The chat request took too long. Please try again.",
          variant: "destructive",
        });
      } else {
        toast({
          title: "Chat failed",
          description: error.message || "Unknown error occurred",
          variant: "destructive",
        });
      }
    }
  };
  const exportDataset = async () => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/analysis/dataset`,
        {
          headers: {
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          signal: controller.signal,
        },
      );
      clearTimeout(timeoutId);
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const data = await response.json();
      setDataset(data.dataset);
    } catch (error: any) {
      if (error.name === "AbortError") {
        toast({
          title: "Request timed out",
          description: "The dataset export took too long. Please try again.",
          variant: "destructive",
        });
      } else {
        toast({
          title: "Dataset export failed",
          description: error.message || "Unknown error occurred",
          variant: "destructive",
        });
      }
    }
  };
  const benchmark = async () => {
    if (!repoUrl) {
      toast({
        title: "Repository URL required",
        description: "Please analyze a repository first",
        variant: "destructive",
      });
      return;
    }
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/analysis/benchmark`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          body: JSON.stringify({
            repo_url: repoUrl,
            research_grade: useResearchGrade,
            framework_hint: frameworkHint,
          }),
          signal: controller.signal,
        },
      );
      clearTimeout(timeoutId);
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const data = await response.json();
      setBenchmarkResult(data.runtime);
    } catch (error: any) {
      if (error.name === "AbortError") {
        toast({
          title: "Request timed out",
          description: "The benchmark took too long. Please try again.",
          variant: "destructive",
        });
      } else {
        toast({
          title: "Benchmark failed",
          description: error.message || "Unknown error occurred",
          variant: "destructive",
        });
      }
    }
  };
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    clearCallgraphData();
    handleAnalyze();
  };
  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Visualize Repository</h1>
      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Repository Analysis</CardTitle>
          <CardDescription>
            Enter a GitHub repository URL to generate and visualize its
            callgraph
            {!isAuthenticated && (
              <span className="text-destructive ml-2">
                (You must log in to save results)
              </span>
            )}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4">
            <div className="grid w-full items-center gap-1.5">
              <Label htmlFor="repoUrl">GitHub Repository URL</Label>
              <div className="flex w-full max-w-sm items-center space-x-2">
                <Input
                  id="repoUrl"
                  placeholder="https://github.com/user/repo" // Improved placeholder
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                />
                <Button
                  type="submit"
                  onClick={() => handleAnalyze(0)}
                  disabled={isLoading}
                >
                  {isLoading ? "Analyzing..." : "Analyze"}
                </Button>
              </div>
            </div>
            {/* Research Grade Analysis Checkbox Start */}
            <div className="flex items-center space-x-2 mt-2 mb-2">
              <Checkbox
                id="research-grade"
                checked={useResearchGrade}
                onCheckedChange={(checked) =>
                  setUseResearchGrade(Boolean(checked))
                }
              />
              <Label htmlFor="research-grade" className="text-sm font-medium">
                Enable Research Grade Analysis (slower, more detailed)
              </Label>
            </div>
            {/* Research Grade Analysis Checkbox End */}
            {/* Context Sensitivity Input Start */}
            <div className="flex items-center space-x-2 mt-2 mb-2">
              <Label
                htmlFor="context-sensitivity"
                className="text-sm font-medium whitespace-nowrap"
              >
                Context Sensitivity (k):
              </Label>
              <Input
                id="context-sensitivity"
                type="number"
                value={contextSensitivity}
                onChange={(e) =>
                  setContextSensitivity(parseInt(e.target.value, 10) || 0)
                }
                className="w-20"
                min="0"
                max="5"
              />
            </div>
            {/* Context Sensitivity Input End */}
            {/* Framework Hint Select Start */}
            <div className="grid w-full items-center gap-1.5">
              <Label htmlFor="framework-hint">Framework Hint</Label>
              <Select value={frameworkHint} onValueChange={setFrameworkHint}>
                <SelectTrigger id="framework-hint" className="w-full max-w-sm">
                  <SelectValue placeholder="Select framework" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="django">Django</SelectItem>
                  <SelectItem value="flask">Flask</SelectItem>
                  <SelectItem value="fastapi">FastAPI</SelectItem>
                  <SelectItem value="general">General Python</SelectItem>
                  {/* Add other relevant frameworks as needed */}
                </SelectContent>
              </Select>
            </div>
            {/* Framework Hint Select End */}
            <div className="grid w-full items-center gap-1.5">
              <Label htmlFor="chatQuery">Ask a Question</Label>
              <div className="flex w-full max-w-sm items-center space-x-2">
                <Input
                  id="chatQuery"
                  placeholder="What does this function do?"
                  value={chatQuery}
                  onChange={(e) => setChatQuery(e.target.value)}
                />
                <Button onClick={handleChat}>Ask</Button>
              </div>
              {chatResponse && (
                <div className="mt-2">
                  <p>
                    <strong>Response:</strong> {chatResponse}
                  </p>
                </div>
              )}
            </div>
            <div className="flex gap-2 mt-4">
              <Button
                onClick={exportDataset}
                className="bg-green-500 text-white"
              >
                Export Dataset
              </Button>
              <Button onClick={benchmark} className="bg-purple-500 text-white">
                Benchmark
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>
      {isLoading ? (
        <div className="flex flex-col items-center justify-center p-12">
          <Skeleton className="h-12 w-1/2 mb-4" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : callgraphData && callgraphData.nodes && callgraphData.nodes.length > 0 ? (
        <Tabs defaultValue="visualization" className="mt-4">
          <TabsList>
            <TabsTrigger value="visualization">Interactive Analysis</TabsTrigger>
            <TabsTrigger value="metrics">Metrics</TabsTrigger>
            <TabsTrigger value="details">Function Details</TabsTrigger>
          </TabsList>
          <TabsContent value="visualization" className="mt-4">
            <div className="border rounded-lg overflow-hidden h-[800px]">
              <VisualizationTabs 
                data={callgraphData} 
                repositoryId={repoUrl}
              />
            </div>
          </TabsContent>
          <TabsContent value="metrics" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>Codebase Metrics</CardTitle>
                <CardDescription>
                  Key metrics and statistics about the analyzed codebase
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">
                      {metrics?.functionCount || 0}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Functions
                    </div>
                  </div>
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">
                      {metrics?.dependencyCount || 0}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Dependencies
                    </div>
                  </div>
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">
                      {metrics?.avgComplexity || 0}
                    </div>
                    <div className="text-sm text-muted-foreground">
                      Avg. Complexity
                    </div>
                  </div>
                </div>
                {metrics?.mostComplexFunction && (
                  <div className="mt-6">
                    <h3 className="font-medium mb-2">Most Complex Function</h3>
                    <div className="p-4 border rounded-lg bg-muted">
                      <div className="font-medium">
                        {metrics.mostComplexFunction.id.split(".").pop()}
                      </div>
                      <div className="text-sm text-muted-foreground">
                        Complexity: {metrics.mostComplexFunction.complexity}
                      </div>
                      <div className="text-sm text-muted-foreground truncate">
                        File: {metrics.mostComplexFunction.file}
                      </div>
                    </div>
                  </div>
                )}
                {benchmarkResult && (
                  <div className="mt-6">
                    <h3 className="font-medium mb-2">Benchmark Result</h3>
                    <div className="p-4 border rounded-lg bg-muted">
                      <div className="text-sm text-muted-foreground">
                        Runtime: {benchmarkResult} seconds
                      </div>
                    </div>
                  </div>
                )}
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="details" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>Function Details</CardTitle>
                <CardDescription>
                  Detailed information about each function in the codebase
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {callgraphData.nodes &&
                  callgraphData.nodes.length > 0 ? (
                    callgraphData.nodes
                      .sort(
                        (a: CallgraphNode, b: CallgraphNode) =>
                          (b.complexity || 0) - (a.complexity || 0),
                      ) 
                      .map((node: CallgraphNode) => (
                        <div key={node.id} className="p-4 border rounded-lg">
                          <div className="font-medium">
                            {node.id.split(".").pop()}
                          </div>
                          <div className="text-sm text-muted-foreground">
                            Type: {node.type}, Complexity: {node.complexity}
                          </div>
                          <div className="text-sm text-muted-foreground truncate">
                            File: {node.file}
                          </div>
                          {node.class && (
                            <div className="text-sm text-muted-foreground">
                              Class: {node.class?.split(".").pop()}
                            </div>
                          )}
                          <div className="text-sm text-muted-foreground">
                            Documentation: {node.metadata?.docstring || "N/A"}
                          </div>
                          <div className="text-sm text-muted-foreground">
                            Refactoring Suggestion:{" "}
                            {node.metadata?.refactoring || "N/A"}
                          </div>
                        </div>
                      ))
                  ) : (
                    <p>No node data available.</p>
                  )}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      ) : (
        <Tabs defaultValue="empty" className="mt-4">
          <TabsList className="hidden">
            <TabsTrigger value="empty">Empty</TabsTrigger>
          </TabsList>
          <TabsContent value="empty">
            <div className="flex flex-col items-center justify-center p-12 text-center">
              <GithubIcon className="h-16 w-16 text-muted-foreground mb-4" />
              <h3 className="text-xl font-medium mb-2">
                No repository analyzed yet
              </h3>
              <p className="text-muted-foreground mb-4">
                Enter a GitHub repository URL above and click Analyze to visualize
                its callgraph
              </p>
            </div>
          </TabsContent>
        </Tabs>
      )}
      {dataset.length > 0 && (
        <Card className="mt-8">
          <CardHeader>
            <CardTitle>Exported Dataset</CardTitle>
            <CardDescription>Dataset for research purposes</CardDescription>
          </CardHeader>
          <CardContent>
            <pre>{JSON.stringify(dataset, null, 2)}</pre>
          </CardContent>
        </Card>
      )}
    </div>
  );
}