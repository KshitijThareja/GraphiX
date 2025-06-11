"use client"

import { createContext, useContext, ReactNode, useState, useEffect } from "react"
import { getToken, getUser, isAuthenticated, removeToken, setToken, User } from "@/lib/auth"
import { useRouter, usePathname, useSearchParams } from "next/navigation"

interface AuthContextType {
    user: User | null
    isAuthenticated: boolean
    login: () => Promise<void>
    logout: () => void
    loading: boolean
}

const AuthContext = createContext<AuthContextType | undefined>(undefined)

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<User | null>(null)
    const [isAuth, setIsAuth] = useState(false) // Track authentication state
    const [loading, setLoading] = useState(true)
    const router = useRouter()
    const pathname = usePathname()
    const searchParams = useSearchParams()

    // Load user data only on the client side
    useEffect(() => {
        async function loadUser() {
            const token = getToken()
            if (token) {
                const userData = getUser()
                setUser(userData)
                setIsAuth(true)
            } else {
                setIsAuth(false)
            }
            setLoading(false)
        }

        loadUser()
    }, [])

    // Handle OAuth callback
    useEffect(() => {
        async function handleCallback() {
            const code = searchParams.get("code")
            if (pathname === "/api/auth/callback/github" && code) {
                try {
                    const response = await fetch(`${process.env.NEXT_PUBLIC_API_URL}/auth/callback?code=${code}`, {
                        method: "GET",
                        headers: {
                            "Content-Type": "application/json",
                        },
                    })

                    if (!response.ok) {
                        throw new Error("Failed to exchange code for token")
                    }

                    const data = await response.json()
                    const { access_token, user } = data

                    setToken(access_token)
                    localStorage.setItem("user", JSON.stringify(user))
                    setUser(user)
                    setIsAuth(true)

                    router.push("/")
                } catch (error) {
                    console.error("Callback handling failed:", error)
                    router.push("/?error=auth_failed")
                }
            }
        }

        handleCallback()
    }, [pathname, searchParams, router])

    const login = async () => {
        try {
            const response = await fetch(`/api/backend/auth/login`, {
                method: "GET",
                headers: {
                    "Content-Type": "application/json",
                },
            })

            if (!response.ok) {
                throw new Error("Failed to fetch GitHub OAuth URL")
            }

            const data = await response.json()
            const githubOAuthUrl = data.url

            if (!githubOAuthUrl) {
                throw new Error("GitHub OAuth URL not found in response")
            }

            window.location.href = githubOAuthUrl
        } catch (error) {
            console.error("Login failed:", error)
            router.push("/?error=login_failed")
        }
    }

    const logout = () => {
        removeToken()
        localStorage.removeItem("user")
        setUser(null)
        setIsAuth(false)
        router.push("/")
    }

    const value = {
        user,
        isAuthenticated: isAuth,
        login,
        logout,
        loading,
    }

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
    const context = useContext(AuthContext)
    if (context === undefined) {
        throw new Error("useAuth must be used within an AuthProvider")
    }
    return context
}