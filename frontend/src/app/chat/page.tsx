"use client"

import type React from "react"

import { useState, useRef, useEffect } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { ScrollArea } from "@/components/ui/scroll-area"
import { SendIcon, BotIcon, UserIcon } from "lucide-react"

interface Message {
  role: "user" | "assistant"
  content: string
  timestamp: Date
}

export default function ChatPage() {
  const [messages, setMessages] = useState<Message[]>([
    {
      role: "assistant",
      content:
        "Hello! I'm the GraphiX AI assistant. I can help you understand your codebase. What would you like to know about your repository?",
      timestamp: new Date(),
    },
  ])
  const [input, setInput] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const messagesEndRef = useRef<HTMLDivElement>(null)

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }

  useEffect(() => {
    scrollToBottom()
  }, [messages])

  const handleSendMessage = async () => {
    if (!input.trim()) return

    const userMessage: Message = {
      role: "user",
      content: input,
      timestamp: new Date(),
    }

    setMessages((prev) => [...prev, userMessage])
    setInput("")
    setIsLoading(true)

    // In a real implementation, this would call the FastAPI backend with OpenAI integration
    // For now, we'll simulate a response after a delay
    setTimeout(() => {
      const responses = [
        "Based on the callgraph analysis, the `process_data` function is the most complex with a cyclomatic complexity of 8. It has multiple dependencies and might be a good candidate for refactoring.",
        "The repository structure shows a typical MVC pattern. The controller functions have high coupling with the model layer, which could be improved by introducing a service layer.",
        "Looking at the code, I notice that error handling is inconsistent across modules. The `log_error` function is called from multiple places but with different parameters.",
        "The `validate_input` function is well-designed with clear validation rules. It's called by `process_data` and helps maintain data integrity throughout the application.",
        "There appears to be a potential memory leak in the `transform_data` function. It allocates resources but doesn't properly release them in all code paths.",
      ]

      const randomResponse = responses[Math.floor(Math.random() * responses.length)]

      const assistantMessage: Message = {
        role: "assistant",
        content: randomResponse,
        timestamp: new Date(),
      }

      setMessages((prev) => [...prev, assistantMessage])
      setIsLoading(false)
    }, 1500)
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSendMessage()
    }
  }

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Chat with LLM</h1>

      <Card className="h-[calc(100vh-200px)] flex flex-col">
        <CardHeader>
          <CardTitle>Repository Assistant</CardTitle>
          <CardDescription>Ask questions about your codebase and get intelligent responses</CardDescription>
        </CardHeader>
        <CardContent className="flex-1 overflow-hidden">
          <ScrollArea className="h-full pr-4">
            <div className="space-y-4">
              {messages.map((message, index) => (
                <div key={index} className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div className={`flex gap-3 max-w-[80%] ${message.role === "user" ? "flex-row-reverse" : ""}`}>
                    <Avatar>
                      <AvatarFallback>
                        {message.role === "user" ? <UserIcon className="h-5 w-5" /> : <BotIcon className="h-5 w-5" />}
                      </AvatarFallback>
                    </Avatar>
                    <div
                      className={`rounded-lg p-4 ${
                        message.role === "user" ? "bg-primary text-primary-foreground" : "bg-muted"
                      }`}
                    >
                      <p className="text-sm">{message.content}</p>
                      <p className="text-xs mt-1 opacity-70">{message.timestamp.toLocaleTimeString()}</p>
                    </div>
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="flex gap-3 max-w-[80%]">
                    <Avatar>
                      <AvatarFallback>
                        <BotIcon className="h-5 w-5" />
                      </AvatarFallback>
                    </Avatar>
                    <div className="rounded-lg p-4 bg-muted">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-2 rounded-full bg-primary animate-pulse"></div>
                        <div className="h-2 w-2 rounded-full bg-primary animate-pulse delay-150"></div>
                        <div className="h-2 w-2 rounded-full bg-primary animate-pulse delay-300"></div>
                        <span className="text-sm">Thinking...</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>
        </CardContent>
        <CardFooter>
          <div className="flex w-full items-center space-x-2">
            <Input
              placeholder="Ask a question about your codebase..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
            />
            <Button size="icon" onClick={handleSendMessage} disabled={isLoading || !input.trim()}>
              <SendIcon className="h-4 w-4" />
            </Button>
          </div>
        </CardFooter>
      </Card>
    </div>
  )
}
