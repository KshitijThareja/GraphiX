"use client"

import type React from "react"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { GitlabIcon as GitHubLogoIcon, FolderIcon, BarChart3Icon, MessageSquareIcon, FileTextIcon } from "lucide-react"
import Link from "next/link"
import { useToast } from "@/components/ui/use-toast"

interface Repository {
  id: number
  name: string
  description: string
  url: string
  stars: number
  lastAnalyzed?: string
}

export default function RepositoriesPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [repositories, setRepositories] = useState<Repository[]>([])
  const { toast } = useToast()

  const handleSearch = async () => {
    if (!searchQuery) {
      toast({
        title: "Search query required",
        description: "Please enter a search term to find repositories",
        variant: "destructive",
      })
      return
    }

    setIsLoading(true)

    // In a real implementation, this would call the FastAPI backend to search GitHub
    // For now, we'll simulate a response after a delay
    setTimeout(() => {
      // Sample repository data for demonstration
      const sampleRepos = [
        {
          id: 1,
          name: "tensorflow/tensorflow",
          description: "An Open Source Machine Learning Framework for Everyone",
          url: "https://github.com/tensorflow/tensorflow",
          stars: 178000,
          lastAnalyzed: "2023-10-15",
        },
        {
          id: 2,
          name: "facebook/react",
          description: "A declarative, efficient, and flexible JavaScript library for building user interfaces",
          url: "https://github.com/facebook/react",
          stars: 215000,
        },
        {
          id: 3,
          name: "django/django",
          description: "The Web framework for perfectionists with deadlines",
          url: "https://github.com/django/django",
          stars: 72000,
          lastAnalyzed: "2023-11-02",
        },
        {
          id: 4,
          name: "microsoft/vscode",
          description: "Visual Studio Code",
          url: "https://github.com/microsoft/vscode",
          stars: 154000,
        },
      ]

      setRepositories(sampleRepos)
      setIsLoading(false)

      toast({
        title: "Repositories found",
        description: `Found ${sampleRepos.length} repositories matching "${searchQuery}"`,
      })
    }, 1500)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch()
    }
  }

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">GitHub Repositories</h1>

      <Card className="mb-8">
        <CardHeader>
          <CardTitle>Search Repositories</CardTitle>
          <CardDescription>Search for GitHub repositories to analyze with GraphiX</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-col gap-4">
            <div className="grid w-full items-center gap-1.5">
              <Label htmlFor="search">Search Query</Label>
              <div className="flex w-full max-w-sm items-center space-x-2">
                <Input
                  id="search"
                  placeholder="tensorflow, react, django..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  onKeyDown={handleKeyDown}
                />
                <Button type="submit" onClick={handleSearch} disabled={isLoading}>
                  {isLoading ? "Searching..." : "Search"}
                </Button>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>

      {repositories.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {repositories.map((repo) => (
            <Card key={repo.id} className="transition-all hover:shadow-md">
              <CardHeader>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <GitHubLogoIcon className="h-5 w-5" />
                    <CardTitle className="text-lg">{repo.name}</CardTitle>
                  </div>
                  <div className="flex items-center text-sm text-muted-foreground">
                    <span>⭐ {repo.stars.toLocaleString()}</span>
                  </div>
                </div>
                <CardDescription>{repo.description}</CardDescription>
              </CardHeader>
              <CardContent>
                <div className="flex items-center text-sm">
                  <FolderIcon className="h-4 w-4 mr-2 text-muted-foreground" />
                  <a href={repo.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">
                    {repo.url}
                  </a>
                </div>
                {repo.lastAnalyzed && (
                  <div className="mt-2 text-sm text-muted-foreground">Last analyzed: {repo.lastAnalyzed}</div>
                )}
              </CardContent>
              <CardFooter className="flex gap-2">
                <Button asChild variant="default" size="sm">
                  <Link href={`/visualize?repo=${encodeURIComponent(repo.url)}`}>
                    <BarChart3Icon className="h-4 w-4 mr-2" />
                    Visualize
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href={`/chat?repo=${encodeURIComponent(repo.url)}`}>
                    <MessageSquareIcon className="h-4 w-4 mr-2" />
                    Chat
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm">
                  <Link href={`/documentation?repo=${encodeURIComponent(repo.url)}`}>
                    <FileTextIcon className="h-4 w-4 mr-2" />
                    Docs
                  </Link>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      ) : (
        <div className="flex flex-col items-center justify-center p-12 text-center">
          <GitHubLogoIcon className="h-16 w-16 text-muted-foreground mb-4" />
          <h3 className="text-xl font-medium mb-2">No repositories found</h3>
          <p className="text-muted-foreground mb-4">Search for GitHub repositories above to get started</p>
        </div>
      )}
    </div>
  )
}
