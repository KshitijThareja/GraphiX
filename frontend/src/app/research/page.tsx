"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Checkbox } from "@/components/ui/checkbox"
import { DownloadIcon, BarChart3Icon, DatabaseIcon, GitlabIcon as GitHubIcon } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"
import { useAuth } from "@/providers/auth-provider"
import { useCallgraph } from "@/context/CallgraphContext"

export default function ResearchPage() {
  const { repoUrl, callgraphData } = useCallgraph()
  const [selectedLanguage, setSelectedLanguage] = useState("python")
  const [repoCount, setRepoCount] = useState("10")
  const [selectedMetrics, setSelectedMetrics] = useState<string[]>(["complexity", "coupling", "cohesion"])
  const { toast } = useToast()
  const { isAuthenticated } = useAuth()

  const handleMetricChange = (metric: string) => {
    if (selectedMetrics.includes(metric)) {
      setSelectedMetrics(selectedMetrics.filter((m) => m !== metric))
    } else {
      setSelectedMetrics([...selectedMetrics, metric])
    }
  }

  const handleGenerateDataset = async () => {
    if (!isAuthenticated) {
      toast({
        title: "Authentication required",
        description: "Please log in to generate a dataset",
        variant: "destructive",
      })
      return
    }

    try {
      const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/dataset`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        },
        body: JSON.stringify({
          language: selectedLanguage,
          repo_count: parseInt(repoCount),
          metrics: selectedMetrics
        })
      })

      if (!response.ok) {
        throw new Error(await response.text())
      }

      const data = await response.json()
      toast({
        title: "Dataset generated",
        description: `Generated dataset for ${repoCount} ${selectedLanguage} repositories`,
      })
    } catch (error) {
      toast({
        title: "Dataset generation failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    }
  }

  const handleDownloadDataset = async () => {
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
      const blob = new Blob([JSON.stringify(data.dataset, null, 2)], { type: "application/json" })
      const url = window.URL.createObjectURL(blob)
      const a = document.createElement("a")
      a.href = url
      a.download = "dataset.json"
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      window.URL.revokeObjectURL(url)

      toast({
        title: "Dataset downloaded",
        description: "The research dataset has been downloaded as a JSON file",
      })
    } catch (error) {
      toast({
        title: "Dataset download failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    }
  }

  const metrics = [
    { id: "complexity", label: "Cyclomatic Complexity" },
    { id: "coupling", label: "Coupling" },
    { id: "cohesion", label: "Cohesion" },
    { id: "loc", label: "Lines of Code" },
    { id: "comments", label: "Comment Ratio" },
    { id: "dependencies", label: "Dependencies" },
    { id: "callgraph_density", label: "Callgraph Density" },
    { id: "llm_accuracy", label: "LLM Analysis Accuracy" },
  ]

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Research Features</h1>

      <Tabs defaultValue="dataset" className="w-full">
        <TabsList className="grid w-full grid-cols-3">
          <TabsTrigger value="dataset">Dataset Generation</TabsTrigger>
          <TabsTrigger value="benchmarking">Benchmarking</TabsTrigger>
          <TabsTrigger value="metrics">Empirical Metrics</TabsTrigger>
        </TabsList>

        <TabsContent value="dataset" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Generate Research Dataset</CardTitle>
              <CardDescription>Create a dataset of callgraphs, code, and LLM outputs for research</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid gap-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div className="space-y-4">
                    <div>
                      <Label htmlFor="language">Programming Language</Label>
                      <Select value={selectedLanguage} onValueChange={setSelectedLanguage}>
                        <SelectTrigger id="language">
                          <SelectValue placeholder="Select language" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="python">Python</SelectItem>
                          <SelectItem value="javascript">JavaScript</SelectItem>
                          <SelectItem value="java">Java</SelectItem>
                          <SelectItem value="cpp">C++</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div>
                      <Label htmlFor="repoCount">Number of Repositories</Label>
                      <Select value={repoCount} onValueChange={setRepoCount}>
                        <SelectTrigger id="repoCount">
                          <SelectValue placeholder="Select count" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="10">10 repositories</SelectItem>
                          <SelectItem value="50">50 repositories</SelectItem>
                          <SelectItem value="100">100 repositories</SelectItem>
                          <SelectItem value="500">500 repositories</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>
                  </div>

                  <div>
                    <Label className="mb-2 block">Metrics to Include</Label>
                    <div className="space-y-2">
                      {metrics.map((metric) => (
                        <div key={metric.id} className="flex items-center space-x-2">
                          <Checkbox
                            id={metric.id}
                            checked={selectedMetrics.includes(metric.id)}
                            onCheckedChange={() => handleMetricChange(metric.id)}
                          />
                          <Label htmlFor={metric.id}>{metric.label}</Label>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>

                <div className="bg-muted p-4 rounded-lg">
                  <h4 className="font-medium mb-2">Dataset Preview</h4>
                  <p className="text-sm text-muted-foreground mb-2">
                    This will generate a dataset with the following characteristics:
                  </p>
                  <ul className="text-sm space-y-1">
                    <li>• Language: {selectedLanguage}</li>
                    <li>• Repository count: {repoCount}</li>
                    <li>• Metrics: {selectedMetrics.join(", ")}</li>
                    <li>• Format: CSV and JSON</li>
                    <li>• Includes: Callgraphs, code snippets, LLM analysis</li>
                  </ul>
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-end gap-2">
              <Button onClick={handleGenerateDataset}>
                <DatabaseIcon className="h-4 w-4 mr-2" />
                Generate Dataset
              </Button>
              <Button variant="outline" onClick={handleDownloadDataset}>
                <DownloadIcon className="h-4 w-4 mr-2" />
                Download Sample
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>

        <TabsContent value="benchmarking" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Benchmark Against Baselines</CardTitle>
              <CardDescription>Compare GraphiX performance for: {repoUrl || "No repository selected"}</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <Label htmlFor="baseline">Baseline Tool</Label>
                    <Select defaultValue="sonarqube">
                      <SelectTrigger id="baseline">
                        <SelectValue placeholder="Select baseline" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="sonarqube">SonarQube</SelectItem>
                        <SelectItem value="codeclimate">CodeClimate</SelectItem>
                        <SelectItem value="pylint">Pylint</SelectItem>
                        <SelectItem value="eslint">ESLint</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>

                  <div>
                    <Label htmlFor="metric">Comparison Metric</Label>
                    <Select defaultValue="runtime">
                      <SelectTrigger id="metric">
                        <SelectValue placeholder="Select metric" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="precision">Precision</SelectItem>
                        <SelectItem value="recall">Recall</SelectItem>
                        <SelectItem value="f1">F1 Score</SelectItem>
                        <SelectItem value="runtime">Runtime</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="bg-muted p-4 rounded-lg">
                  <h4 className="font-medium mb-2">Benchmark Results</h4>
                  <p className="text-sm text-muted-foreground">
                    No benchmark has been run yet. Configure the parameters and click "Run Benchmark".
                  </p>
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-end">
              <Button onClick={async () => {
                if (!repoUrl) {
                  toast({
                    title: "No repository selected",
                    description: "Please analyze a repository in the Visualize page first",
                    variant: "destructive",
                  })
                  return
                }
                try {
                  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/benchmark`, {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": `Bearer ${localStorage.getItem("token")}`
                    },
                    body: JSON.stringify({ repo_url: repoUrl })
                  })
                  if (!response.ok) throw new Error(await response.text())
                  const data = await response.json()
                  toast({
                    title: "Benchmark completed",
                    description: `Runtime: ${data.runtime} seconds`,
                  })
                } catch (error) {
                  toast({
                    title: "Benchmark failed",
                    description: error instanceof Error ? error.message : "Unknown error",
                    variant: "destructive",
                  })
                }
              }}>
                <BarChart3Icon className="h-4 w-4 mr-2" />
                Run Benchmark
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>

        <TabsContent value="metrics" className="mt-6">
          <Card>
            <CardHeader>
              <CardTitle>Empirical Metrics Collection</CardTitle>
              <CardDescription>
                Gather quantitative data for: {repoUrl || "No repository selected"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="space-y-6">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                  <div>
                    <Label htmlFor="repoList">Repository List</Label>
                    <Input 
                      id="repoList" 
                      placeholder="Enter GitHub repository URLs (one per line)" 
                      className="h-32" 
                      value={repoUrl ? repoUrl : ""}
                      onChange={(e) => {
                        // Allow manual input if needed, but prefill with repoUrl
                      }}
                    />
                  </div>

                  <div className="space-y-4">
                    <div>
                      <Label htmlFor="outputFormat">Output Format</Label>
                      <Select defaultValue="csv">
                        <SelectTrigger id="outputFormat">
                          <SelectValue placeholder="Select format" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="csv">CSV</SelectItem>
                          <SelectItem value="json">JSON</SelectItem>
                          <SelectItem value="excel">Excel</SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="flex items-center space-x-2">
                      <Checkbox id="reproducible" />
                      <Label htmlFor="reproducible">Enable reproducibility mode (fixed seeds)</Label>
                    </div>
                  </div>
                </div>
              </div>
            </CardContent>
            <CardFooter className="flex justify-end gap-2">
              <Button onClick={async () => {
                if (!repoUrl) {
                  toast({
                    title: "No repository selected",
                    description: "Please analyze a repository in the Visualize page first",
                    variant: "destructive",
                  })
                  return
                }
                try {
                  const repoList = (document.getElementById("repoList") as HTMLInputElement).value.split("\n")
                  const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/dataset`, {
                    method: "POST",
                    headers: {
                      "Content-Type": "application/json",
                      "Authorization": `Bearer ${localStorage.getItem("token")}`
                    },
                    body: JSON.stringify({
                      language: "python",
                      repo_count: repoList.length,
                      metrics: selectedMetrics
                    })
                  })
                  if (!response.ok) throw new Error(await response.text())
                  const data = await response.json()
                  toast({
                    title: "Metrics collected",
                    description: "Metrics have been collected successfully",
                  })
                } catch (error) {
                  toast({
                    title: "Metrics collection failed",
                    description: error instanceof Error ? error.message : "Unknown error",
                    variant: "destructive",
                  })
                }
              }}>
                <GitHubIcon className="h-4 w-4 mr-2" />
                Collect Metrics
              </Button>
              <Button variant="outline" onClick={handleDownloadDataset}>
                <DownloadIcon className="h-4 w-4 mr-2" />
                Export Template
              </Button>
            </CardFooter>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}