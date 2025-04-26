"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Badge } from "@/components/ui/badge"
import { RefreshCwIcon, AlertTriangleIcon, CheckCircleIcon, XCircleIcon } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"

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

  const handleApply = (id: string) => {
    toast({
      title: "Refactoring applied",
      description: `The refactoring suggestion ${id} has been applied to your codebase`,
    })
  }

  const handleApplyAll = () => {
    toast({
      title: "All refactorings applied",
      description: "All refactoring suggestions have been applied to your codebase",
    })
  }

  const refactoringSuggestions: RefactoringItem[] = [
    {
      id: "REF-001",
      title: "Extract Method in process_data",
      description:
        "The process_data function is too complex (complexity: 8). Extract the data transformation logic into a separate method.",
      severity: "high",
      location: "main.py:45-67",
      before: `def process_data(data):
    # Validate input
    if not validate_input(data):
        log_error("Invalid input data")
        return None
        
    # Transform data - this part is complex and should be extracted
    result = {}
    for key, value in data.items():
        if key.startswith("user_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["name"] = value
        elif key.startswith("score_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["score"] = int(value)
    
    # Save results
    if not save_results(result):
        log_error("Failed to save results")
        return None
        
    return result`,
      after: `def process_data(data):
    # Validate input
    if not validate_input(data):
        log_error("Invalid input data")
        return None
        
    # Extract transformation to a new method
    result = transform_user_data(data)
    
    # Save results
    if not save_results(result):
        log_error("Failed to save results")
        return None
        
    return result
    
def transform_user_data(data):
    result = {}
    for key, value in data.items():
        if key.startswith("user_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["name"] = value
        elif key.startswith("score_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["score"] = int(value)
    return result`,
    },
    {
      id: "REF-002",
      title: "Add Error Handling in transform_data",
      description: "The transform_data function doesn't handle potential exceptions when processing data.",
      severity: "medium",
      location: "transform.py:23-35",
      before: `def transform_data(data):
    result = {}
    for item in data:
        key = item["id"]
        value = process_item(item)
        result[key] = value
    return result`,
      after: `def transform_data(data):
    result = {}
    for item in data:
        try:
            key = item["id"]
            value = process_item(item)
            result[key] = value
        except KeyError:
            log_error(f"Missing 'id' in item: {item}")
        except Exception as e:
            log_error(f"Error processing item: {str(e)}")
    return result`,
    },
    {
      id: "REF-003",
      title: "Use Constants for Magic Strings",
      description: "Replace magic strings with named constants for better maintainability.",
      severity: "low",
      location: "utils.py:12-18",
      before: `def get_status(code):
    if code == "A":
        return "Active"
    elif code == "I":
        return "Inactive"
    elif code == "P":
        return "Pending"
    return "Unknown"`,
      after: `# Define constants at the module level
STATUS_ACTIVE = "A"
STATUS_INACTIVE = "I"
STATUS_PENDING = "P"

def get_status(code):
    if code == STATUS_ACTIVE:
        return "Active"
    elif code == STATUS_INACTIVE:
        return "Inactive"
    elif code == STATUS_PENDING:
        return "Pending"
    return "Unknown"`,
    },
  ]

  const filteredSuggestions =
    selectedTab === "all"
      ? refactoringSuggestions
      : refactoringSuggestions.filter((item) => item.severity === selectedTab)

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
