"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { GitlabIcon as GitHubLogoIcon } from "lucide-react"
import CallgraphVisualization from "@/components/callgraph-visualization"
import { useToast } from "@/components/ui/use-toast"
import { useAuth } from "@/providers/auth-provider"
import { Skeleton } from "@/components/ui/skeleton"

export default function VisualizePage() {
  const [repoUrl, setRepoUrl] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [callgraphData, setCallgraphData] = useState<any>(null)
  const [metrics, setMetrics] = useState<any>(null)
  const [chatQuery, setChatQuery] = useState("")
  const [chatResponse, setChatResponse] = useState("")
  const [dataset, setDataset] = useState<any[]>([])
  const [benchmarkResult, setBenchmarkResult] = useState<number | null>(null)
  const { toast } = useToast()
  const { isAuthenticated } = useAuth()

  const handleAnalyze = async () => {
    if (!repoUrl) {
      toast({
        title: "Repository URL required",
        description: "Please enter a valid GitHub repository URL",
        variant: "destructive",
      })
      return
    }

    setIsLoading(true)
    setCallgraphData(null)
    setMetrics(null)

    try {
      const response = await fetch(`/api/backend/analysis/callgraph`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        },
        body: JSON.stringify({
          repo_url: repoUrl
        })
      })

      if (!response.ok) {
        throw new Error(await response.text())
      }

      const data = await response.json()
      setCallgraphData(data)

      const calculatedMetrics = {
        functionCount: data.nodes.length,
        dependencyCount: data.links.length,
        avgComplexity: parseFloat(
          (data.nodes.reduce((sum: number, node: any) => sum + node.complexity, 0) / 
          data.nodes.length).toFixed(1)
        ),
        mostComplexFunction: data.nodes.reduce(
          (max: any, node: any) => (node.complexity > max.complexity ? node : max),
          { complexity: -1 }
        )
      }
      setMetrics(calculatedMetrics)

      toast({
        title: "Repository analyzed",
        description: "Callgraph generated successfully",
      })
    } catch (error) {
      console.error("Analysis failed:", error)
      toast({
        title: "Analysis failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }

  const handleChat = async () => {
    if (!chatQuery) {
      toast({
        title: "Query required",
        description: "Please enter a chat query",
        variant: "destructive",
      })
      return
    }

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        },
        body: JSON.stringify({
          query: chatQuery
        })
      })

      if (!response.ok) {
        throw new Error(await response.text())
      }

      const data = await response.json()
      setChatResponse(data.response)
    } catch (error) {
      toast({
        title: "Chat failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    }
  }

  const exportDataset = async () => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/dataset`, {
        headers: {
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        }
      })
      if (!response.ok) {
        throw new Error(await response.text())
      }
      const data = await response.json()
      setDataset(data.dataset)
    } catch (error) {
      toast({
        title: "Dataset export failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    }
  }

  const benchmark = async () => {
    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/benchmark`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        },
        body: JSON.stringify({
          repo_url: repoUrl
        })
      })
      if (!response.ok) {
        throw new Error(await response.text())
      }
      const data = await response.json()
      setBenchmarkResult(data.runtime)
    } catch (error) {
      toast({
        title: "Benchmark failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    }
  }

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Visualize Repository</h1>

      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Repository Analysis</CardTitle>
          <CardDescription>
            Enter a GitHub repository URL to generate and visualize its callgraph
            {!isAuthenticated && (
              <span className="text-destructive ml-2">
                (Login required for private repositories)
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
                  placeholder="https://github.com/username/repository"
                  value={repoUrl}
                  onChange={(e) => setRepoUrl(e.target.value)}
                />
                <Button
                  type="submit"
                  onClick={handleAnalyze}
                  disabled={isLoading}
                >
                  {isLoading ? "Analyzing..." : "Analyze"}
                </Button>
                <Button onClick={exportDataset} className="bg-green-500 text-white p-2 ml-2">
                  Export Dataset
                </Button>
                <Button onClick={benchmark} className="bg-purple-500 text-white p-2 ml-2">
                  Benchmark
                </Button>
              </div>
            </div>
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
                  <p><strong>Response:</strong> {chatResponse}</p>
                </div>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {isLoading ? (
        <div className="space-y-4">
          <Skeleton className="h-[600px] w-full rounded-lg" />
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        </div>
      ) : callgraphData ? (
        <Tabs defaultValue="visualization" className="w-full">
          <TabsList className="grid w-full grid-cols-3">
            <TabsTrigger value="visualization">Visualization</TabsTrigger>
            <TabsTrigger value="metrics">Metrics</TabsTrigger>
            <TabsTrigger value="details">Details</TabsTrigger>
          </TabsList>
          <TabsContent value="visualization" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>Callgraph Visualization</CardTitle>
                <CardDescription>
                  Interactive visualization of function calls and dependencies
                </CardDescription>
              </CardHeader>
              <CardContent className="h-[600px]">
                <CallgraphVisualization data={callgraphData} />
              </CardContent>
            </Card>
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
                    <div className="text-sm text-muted-foreground">Functions</div>
                  </div>
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">
                      {metrics?.dependencyCount || 0}
                    </div>
                    <div className="text-sm text-muted-foreground">Dependencies</div>
                  </div>
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">
                      {metrics?.avgComplexity || 0}
                    </div>
                    <div className="text-sm text-muted-foreground">Avg. Complexity</div>
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
                  {callgraphData.nodes
                    .sort((a: any, b: any) => b.complexity - a.complexity)
                    .map((node: any) => (
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
                          Documentation: {node.metadata?.docstring || 'N/A'}
                        </div>
                        <div className="text-sm text-muted-foreground">
                          Refactoring Suggestion: {node.metadata?.refactoring || 'N/A'}
                        </div>
                      </div>
                    ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        </Tabs>
      ) : (
        <div className="flex flex-col items-center justify-center p-12 text-center">
          <GitHubLogoIcon className="h-16 w-16 text-muted-foreground mb-4" />
          <h3 className="text-xl font-medium mb-2">No repository analyzed yet</h3>
          <p className="text-muted-foreground mb-4">
            Enter a GitHub repository URL above and click Analyze to visualize its callgraph
          </p>
        </div>
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
  )
}