"use client"

import Link from "next/link"
import { ModeToggle } from "./mode-toggle"
import { Button } from "./ui/button"
import {
  GitlabIcon as GitHubLogoIcon,
  HomeIcon,
  BarChartIcon,
  FileTextIcon,
  GitlabIcon as GitHubIcon,
} from "lucide-react"
import { usePathname } from "next/navigation"
import { cn } from "@/lib/utils"

export default function Header() {
  const pathname = usePathname()

  const navItems = [
    { name: "Home", href: "/", icon: HomeIcon },
    { name: "Visualize", href: "/visualize", icon: BarChartIcon },
    { name: "Documentation", href: "/documentation", icon: FileTextIcon },
    { name: "Repositories", href: "/repositories", icon: GitHubIcon },
  ]

  return (
    <header className="border-b">
      <div className="container flex h-16 items-center justify-between">
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2">
            <GitHubLogoIcon className="h-6 w-6" />
            <span className="text-xl font-bold">GraphiX</span>
          </Link>
          <nav className="hidden md:flex gap-6">
            {navItems.map((item) => {
              const Icon = item.icon
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 text-sm font-medium transition-colors hover:text-primary",
                    pathname === item.href ? "text-primary" : "text-muted-foreground",
                  )}
                >
                  <Icon className="h-4 w-4" />
                  {item.name}
                </Link>
              )
            })}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <ModeToggle />
          <Button asChild variant="default" size="sm">
            <Link href="/visualize">Analyze Repository</Link>
          </Button>
        </div>
      </div>
    </header>
  )
}
