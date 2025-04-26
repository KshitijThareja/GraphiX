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

export default function VisualizePage() {
  const [repoUrl, setRepoUrl] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [callgraphData, setCallgraphData] = useState<any>(null)
  const { toast } = useToast()

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

    // In a real implementation, this would call the FastAPI backend
    // For now, we'll simulate a response after a delay
    setTimeout(() => {
      // Sample callgraph data for demonstration
      const sampleData = {
        nodes: [
          { id: "main", group: 1, type: "function", complexity: 5 },
          { id: "process_data", group: 2, type: "function", complexity: 8 },
          { id: "validate_input", group: 2, type: "function", complexity: 3 },
          { id: "transform_data", group: 2, type: "function", complexity: 7 },
          { id: "save_results", group: 3, type: "function", complexity: 4 },
          { id: "log_error", group: 4, type: "function", complexity: 2 },
          { id: "display_output", group: 5, type: "function", complexity: 6 },
        ],
        links: [
          { source: "main", target: "process_data", value: 1 },
          { source: "main", target: "display_output", value: 1 },
          { source: "process_data", target: "validate_input", value: 1 },
          { source: "process_data", target: "transform_data", value: 1 },
          { source: "process_data", target: "save_results", value: 1 },
          { source: "process_data", target: "log_error", value: 1 },
          { source: "transform_data", target: "log_error", value: 1 },
          { source: "save_results", target: "log_error", value: 1 },
        ],
      }

      setCallgraphData(sampleData)
      setIsLoading(false)

      toast({
        title: "Repository analyzed",
        description: "Callgraph generated successfully",
      })
    }, 2000)
  }

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Visualize Repository</h1>

      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Repository Analysis</CardTitle>
          <CardDescription>Enter a GitHub repository URL to generate and visualize its callgraph</CardDescription>
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
                <Button type="submit" onClick={handleAnalyze} disabled={isLoading}>
                  {isLoading ? "Analyzing..." : "Analyze"}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {callgraphData ? (
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
                <CardDescription>Interactive visualization of function calls and dependencies</CardDescription>
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
                <CardDescription>Key metrics and statistics about the analyzed codebase</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">7</div>
                    <div className="text-sm text-muted-foreground">Functions</div>
                  </div>
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">8</div>
                    <div className="text-sm text-muted-foreground">Dependencies</div>
                  </div>
                  <div className="bg-muted p-4 rounded-lg">
                    <div className="text-2xl font-bold">5.0</div>
                    <div className="text-sm text-muted-foreground">Avg. Complexity</div>
                  </div>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
          <TabsContent value="details" className="mt-4">
            <Card>
              <CardHeader>
                <CardTitle>Function Details</CardTitle>
                <CardDescription>Detailed information about each function in the codebase</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  {callgraphData.nodes.map((node: any) => (
                    <div key={node.id} className="p-4 border rounded-lg">
                      <div className="font-medium">{node.id}</div>
                      <div className="text-sm text-muted-foreground">
                        Type: {node.type}, Complexity: {node.complexity}
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
    </div>
  )
}
