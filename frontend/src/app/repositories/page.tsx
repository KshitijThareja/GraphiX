"use client"
import type React from "react"
import { useState, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { GitlabIcon as GitHubLogoIcon, FolderIcon, BarChart3Icon, MessageSquareIcon, FileTextIcon } from "lucide-react"
import Link from "next/link"
import { useToast } from "@/components/ui/use-toast"
import { useAuth } from "@/providers/auth-provider"
import { useCallgraph } from "@/context/CallgraphContext"
interface Repository {
  id: number
  name: string
  description: string
  url: string
  stars: number
}
export default function RepositoriesPage() {
  const [searchQuery, setSearchQuery] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [repositories, setRepositories] = useState<Repository[]>([])
  const { toast } = useToast()
  const { isAuthenticated } = useAuth()
  const { setRepoUrl } = useCallgraph()
  const handleSearch = async () => {
    if (!searchQuery) {
      toast({
        title: "Search query required",
        description: "Please enter a search term to find repositories",
        variant: "destructive",
      })
      return
    }
    if (!isAuthenticated) {
      toast({
        title: "Authentication required",
        description: "Please log in with GitHub to search repositories",
        variant: "destructive",
      })
      return
    }
    setIsLoading(true)
    try {
      const token = localStorage.getItem("token")
      if (!token) {
        throw new Error("No authentication token found. Please log in again.")
      }
      const response = await fetch(`https:
      if (!response.ok) {
        const errorText = await response.text()
        if (response.status === 403) {
          throw new Error("GitHub API rate limit exceeded. Please try again later or authenticate with a higher rate limit.")
        }
        throw new Error(`GitHub API error: ${errorText}`)
      }
      const data = await response.json()
      const repos = data.items.map((item: any) => ({
        id: item.id,
        name: item.full_name,
        description: item.description || "No description",
        url: item.html_url,
        stars: item.stargazers_count,
      }))
      setRepositories(repos)
      toast({
        title: "Repositories found",
        description: `Found ${repos.length} repositories matching "${searchQuery}"`,
      })
    } catch (error) {
      console.error("Search error:", error)
      toast({
        title: "Search failed",
        description: error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      })
    } finally {
      setIsLoading(false)
    }
  }
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") {
      handleSearch()
    }
  }
  const handleSelectRepo = (url: string) => {
    setRepoUrl(url)
    toast({
      title: "Repository selected",
      description: `Selected repository: ${url}`,
    })
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
              </CardContent>
              <CardFooter className="flex gap-2">
                <Button asChild variant="default" size="sm" onClick={() => handleSelectRepo(repo.url)}>
                  <Link href={`/visualize`}>
                    <BarChart3Icon className="h-4 w-4 mr-2" />
                    Visualize
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm" onClick={() => handleSelectRepo(repo.url)}>
                  <Link href={`/chat`}>
                    <MessageSquareIcon className="h-4 w-4 mr-2" />
                    Chat
                  </Link>
                </Button>
                <Button asChild variant="outline" size="sm" onClick={() => handleSelectRepo(repo.url)}>
                  <Link href={`/documentation`}>
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