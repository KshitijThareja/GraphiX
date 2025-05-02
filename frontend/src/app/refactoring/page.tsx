"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { RefreshCwIcon, AlertTriangleIcon, CheckCircleIcon, XCircleIcon } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"
import { useSearchParams } from "next/navigation"

interface RefactoringItem {
  id: string
  title: string
  description: string
  severity: "high" | "medium" | "low"
  location: string
  before: string
  after: string
}

export default function RefactoringPage() {
  const [selectedTab, setSelectedTab] = useState("all")
  const { toast } = useToast()
  const searchParams = useSearchParams()
  const [refactoringSuggestions, setRefactoringSuggestions] = useState<RefactoringItem[]>([])
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    const repo = searchParams.get("repo")
    if (repo) {
      setIsLoading(true)
      fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/refactoring`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        },
        body: JSON.stringify({ repo_url: repo })
      })
        .then(res => {
          if (!res.ok) throw new Error("Failed to fetch refactoring suggestions")
          return res.json()
        })
        .then(data => setRefactoringSuggestions(data.suggestions))
        .catch(err => toast({
          title: "Error",
          description: err.message,
          variant: "destructive",
        }))
        .finally(() => setIsLoading(false))
    }
  }, [searchParams])

  const handleApply = (id: string) => {
    toast({
      title: "Refactoring applied",
      description: `The refactoring suggestion ${id} has been applied to your codebase`,
    })
    // TODO: Implement actual code modification (requires file system access)
  }

  const handleApplyAll = () => {
    refactoringSuggestions.forEach((item) => handleApply(item.id))
    toast({
      title: "All refactorings applied",
      description: "All refactoring suggestions have been applied to your codebase",
    })
  }

  const filteredSuggestions =
    selectedTab === "all"
      ? refactoringSuggestions
      : refactoringSuggestions.filter((item) => item.severity === selectedTab)

  if (isLoading) return <div>Loading...</div>

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Refactoring Suggestions</h1>

      <Card>
        <CardHeader>
          <div className="flex items-center justify-between">
            <div>
              <CardTitle>AI-Driven Refactoring</CardTitle>
              <CardDescription>Suggestions to improve your code quality based on callgraph analysis</CardDescription>
            </div>
            <Button onClick={handleApplyAll}>
              <RefreshCwIcon className="h-4 w-4 mr-2" />
              Apply All
            </Button>
          </div>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="all" value={selectedTab} onValueChange={setSelectedTab}>
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="all">
                All
                <Badge variant="outline" className="ml-2">
                  {refactoringSuggestions.length}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="high">
                High Priority
                <Badge variant="outline" className="ml-2">
                  {refactoringSuggestions.filter((item) => item.severity === "high").length}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="medium">
                Medium Priority
                <Badge variant="outline" className="ml-2">
                  {refactoringSuggestions.filter((item) => item.severity === "medium").length}
                </Badge>
              </TabsTrigger>
              <TabsTrigger value="low">
                Low Priority
                <Badge variant="outline" className="ml-2">
                  {refactoringSuggestions.filter((item) => item.severity === "low").length}
                </Badge>
              </TabsTrigger>
            </TabsList>

            <TabsContent value={selectedTab} className="mt-6">
              <div className="space-y-6">
                {filteredSuggestions.map((suggestion) => (
                  <Card key={suggestion.id}>
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-3">
                          {suggestion.severity === "high" && <AlertTriangleIcon className="h-5 w-5 text-destructive" />}
                          {suggestion.severity === "medium" && <AlertTriangleIcon className="h-5 w-5 text-amber-500" />}
                          {suggestion.severity === "low" && (
                            <AlertTriangleIcon className="h-5 w-5 text-muted-foreground" />
                          )}
                          <div>
                            <CardTitle className="text-lg flex items-center gap-2">
                              {suggestion.title}
                              <Badge
                                variant={
                                  suggestion.severity === "high"
                                    ? "destructive"
                                    : suggestion.severity === "medium"
                                      ? "default"
                                      : "outline"
                                }
                              >
                                {suggestion.severity} priority
                              </Badge>
                            </CardTitle>
                            <CardDescription>{suggestion.description}</CardDescription>
                          </div>
                        </div>
                        <Badge variant="outline">{suggestion.location}</Badge>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                        <div>
                          <div className="flex items-center mb-2">
                            <XCircleIcon className="h-4 w-4 text-destructive mr-2" />
                            <h4 className="font-medium">Before</h4>
                          </div>
                          <pre className="bg-muted p-4 rounded-lg overflow-auto text-sm">
                            <code>{suggestion.before}</code>
                          </pre>
                        </div>
                        <div>
                          <div className="flex items-center mb-2">
                            <CheckCircleIcon className="h-4 w-4 text-green-500 mr-2" />
                            <h4 className="font-medium">After</h4>
                          </div>
                          <pre className="bg-muted p-4 rounded-lg overflow-auto text-sm">
                            <code>{suggestion.after}</code>
                          </pre>
                        </div>
                      </div>
                    </CardContent>
                    <CardFooter className="flex justify-end">
                      <Button onClick={() => handleApply(suggestion.id)}>Apply Refactoring</Button>
                    </CardFooter>
                  </Card>
                ))}
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>
    </div>
  )
}