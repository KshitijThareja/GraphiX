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
import { useAuth } from "@/providers/auth-provider"
import { Avatar, AvatarFallback, AvatarImage } from "./ui/avatar"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "./ui/dropdown-menu"

export default function Header() {
  const pathname = usePathname()
  const { user, isAuthenticated, login, logout } = useAuth()

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
          {isAuthenticated ? (
            <DropdownMenu>
              <DropdownMenuTrigger>
                <Avatar className="h-8 w-8">
                  <AvatarImage src={user?.avatar_url} />
                  <AvatarFallback>{user?.login?.charAt(0).toUpperCase()}</AvatarFallback>
                </Avatar>
              </DropdownMenuTrigger>
              <DropdownMenuContent>
                <DropdownMenuItem onClick={logout}>Logout</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          ) : (
            <Button onClick={login} variant="default" size="sm">
              Login with GitHub
            </Button>
          )}
        </div>
      </div>
    </header>
  )
}