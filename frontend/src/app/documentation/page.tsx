"use client"

import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DownloadIcon, CopyIcon, CheckIcon } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"
import { useCallgraph } from "@/context/CallgraphContext"

export default function DocumentationPage() {
  const { repoUrl } = useCallgraph()
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()
  const [documentation, setDocumentation] = useState("")
  const [isLoading, setIsLoading] = useState(false)

  useEffect(() => {
    console.log("DocumentationPage: repoUrl from context:", repoUrl)
    if (repoUrl) {
      setIsLoading(true)
      console.log("Fetching documentation for repo:", repoUrl)
      fetch(`${process.env.NEXT_PUBLIC_API_URL}/analysis/documentation`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${localStorage.getItem("token")}`
        },
        body: JSON.stringify({ repo_url: repoUrl })
      })
        .then(res => {
          console.log("Fetch response status:", res.status)
          if (!res.ok) throw new Error(`Failed to fetch documentation: ${res.statusText}`)
          return res.json()
        })
        .then(data => {
          console.log("Documentation fetch successful:", data)
          setDocumentation(data.documentation || "No documentation available.")
        })
        .catch(err => {
          console.error("Documentation fetch error:", err)
          toast({
            title: "Error",
            description: err.message,
            variant: "destructive",
          })
        })
        .finally(() => setIsLoading(false))
    }
  }, [repoUrl, toast])

  const handleCopy = () => {
    navigator.clipboard.writeText(documentation)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
    toast({
      title: "Documentation copied",
      description: "The documentation has been copied to your clipboard",
    })
  }

  const handleDownload = () => {
    const element = document.createElement("a")
    const file = new Blob([documentation], { type: "text/markdown" })
    element.href = URL.createObjectURL(file)
    element.download = "documentation.md"
    document.body.appendChild(element)
    element.click()
    document.body.removeChild(element)
    toast({
      title: "Documentation downloaded",
      description: "The documentation has been downloaded as a Markdown file",
    })
  }

  if (!repoUrl) {
    return (
      <div className="container py-12">
        <h1 className="text-3xl font-bold mb-6">Automated Documentation</h1>
        <Card>
          <CardHeader>
            <CardTitle>Repository Documentation</CardTitle>
            <CardDescription>No repository selected. Please analyze a repository in the Visualize page first.</CardDescription>
          </CardHeader>
        </Card>
      </div>
    )
  }

  if (isLoading) return <div>Loading...</div>

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Automated Documentation</h1>

      <Card>
        <CardHeader>
          <CardTitle>Repository Documentation</CardTitle>
          <CardDescription>
            Automatically generated documentation for: {repoUrl}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="markdown" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="markdown">Markdown</TabsTrigger>
              <TabsTrigger value="preview">Preview</TabsTrigger>
            </TabsList>
            <TabsContent value="markdown" className="mt-4">
              <div className="relative">
                <pre className="bg-muted p-4 rounded-lg overflow-auto max-h-[600px] text-sm">
                  <code>{documentation}</code>
                </pre>
                <div className="absolute top-2 right-2 flex gap-2">
                  <Button variant="outline" size="icon" onClick={handleCopy} className="h-8 w-8">
                    {copied ? <CheckIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </TabsContent>
            <TabsContent value="preview" className="mt-4">
              <div className="bg-background border rounded-lg p-6 overflow-auto max-h-[600px]">
                <div dangerouslySetInnerHTML={{ __html: documentation.replace(/\n/g, "<br>").replace(/#/g, "<h1>").replace(/\*\*/g, "<strong>").replace(/##/g, "</h1><h2>").replace(/###/g, "</h2><h3>") }} />
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
        <CardFooter className="flex justify-end gap-2">
          <Button variant="outline" onClick={handleCopy}>
            <CopyIcon className="h-4 w-4 mr-2" />
            Copy
          </Button>
          <Button onClick={handleDownload}>
            <DownloadIcon className="h-4 w-4 mr-2" />
            Download
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}