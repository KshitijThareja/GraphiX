import { Button } from "@/components/ui/button"
import { Card, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import Link from "next/link"
import { BarChart3Icon, FileTextIcon, GitlabIcon as GitHubIcon, MessageSquareIcon, RefreshCwIcon } from "lucide-react"

export default function Home() {
  const features = [
    {
      icon: <BarChart3Icon className="h-8 w-8 text-primary" />,
      title: "Interactive Callgraph Visualization",
      description: "Visualize code structure with interactive callgraphs enhanced with LLM insights.",
      href: "/visualize",
    },
    // {
    //   icon: <MessageSquareIcon className="h-8 w-8 text-primary" />,
    //   title: "Chat with LLM",
    //   description: "Query your codebase using natural language and get intelligent responses.",
    //   href: "/chat",
    // },
    {
      icon: <FileTextIcon className="h-8 w-8 text-primary" />,
      title: "Automated Documentation",
      description: "Generate comprehensive documentation for your codebase components.",
      href: "/documentation",
    },
    {
      icon: <RefreshCwIcon className="h-8 w-8 text-primary" />,
      title: "Refactoring Suggestions",
      description: "Receive AI-driven recommendations to improve your code quality.",
      href: "/refactoring",
    },
    {
      icon: <GitHubIcon className="h-8 w-8 text-primary" />,
      title: "GitHub Integration",
      description: "Seamlessly connect with GitHub repositories for analysis.",
      href: "/repositories",
    },
  ]

  return (
    <div className="container py-12">
      <section className="py-12 md:py-24 lg:py-32 flex flex-col items-center text-center">
        <h1 className="text-4xl md:text-6xl font-bold tracking-tighter mb-4">
          Evaluate GitHub Codebases with <span className="text-primary">GraphiX</span>
        </h1>
        <p className="text-xl text-muted-foreground max-w-[800px] mb-8">
          Combine callgraphs and Large Language Models to visualize, understand, and improve your code.
        </p>
        <div className="flex flex-wrap gap-4 justify-center">
          <Button asChild size="lg">
            <Link href="/visualize">Analyze Repository</Link>
          </Button>
          <Button asChild variant="outline" size="lg">
            <Link href="/documentation">Learn More</Link>
          </Button>
        </div>
      </section>

      <section className="py-12 md:py-24">
        <h2 className="text-3xl font-bold tracking-tighter mb-12 text-center">Key Features</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {features.map((feature, index) => (
            <Card key={index} className="transition-all hover:shadow-md">
              <CardHeader>
                <div className="mb-4">{feature.icon}</div>
                <CardTitle>{feature.title}</CardTitle>
                <CardDescription>{feature.description}</CardDescription>
              </CardHeader>
              <CardFooter>
                <Button asChild variant="outline" className="w-full">
                  <Link href={feature.href}>Explore</Link>
                </Button>
              </CardFooter>
            </Card>
          ))}
        </div>
      </section>

      <section className="py-12 md:py-24 bg-muted rounded-lg p-8">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-12 items-center">
          <div>
            <h2 className="text-3xl font-bold tracking-tighter mb-4">Research-Oriented Analysis</h2>
            <p className="text-muted-foreground mb-6">
              GraphiX is designed for both developers and researchers, providing tools for dataset generation,
              benchmarking, and empirical analysis of codebases.
            </p>
            <ul className="space-y-2 mb-6">
              <li className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-primary"></div>
                <span>Generate datasets of callgraphs with annotations</span>
              </li>
              <li className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-primary"></div>
                <span>Compare against baseline tools like SonarQube</span>
              </li>
              <li className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-primary"></div>
                <span>Collect empirical metrics for research</span>
              </li>
              <li className="flex items-center gap-2">
                <div className="h-2 w-2 rounded-full bg-primary"></div>
                <span>Support for multiple programming languages</span>
              </li>
            </ul>
            <Button asChild>
              <Link href="/research">Research Features</Link>
            </Button>
          </div>
          <div className="bg-background p-6 rounded-lg border">
            <div className="aspect-video bg-gradient-to-br from-primary/20 to-primary/5 rounded-md flex items-center justify-center">
              <span className="text-primary font-medium">Research Dashboard Preview</span>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}