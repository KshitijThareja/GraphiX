"use client";
import React, { useState, useRef, useEffect } from "react";
import {
  Card,
  CardContent,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { ScrollArea } from "@/components/ui/scroll-area";
import { SendIcon, RefreshCw } from "lucide-react";
import { useToast } from "@/components/ui/use-toast";
import MessageBubble, { MessageProps } from "./MessageBubble";
import CodeContextPanel, { CodeContext } from "./CodeContextPanel";
import { useCallgraph } from "@/context/CallgraphContext";

interface ChatInterfaceProps {
  repositoryId?: string;
  className?: string;
  onHighlightNode?: (nodeId: string) => void;
}

export default function ChatInterface({
  repositoryId,
  className,
  onHighlightNode,
}: ChatInterfaceProps) {
  const { repoUrl } = useCallgraph();
  const [messages, setMessages] = useState<MessageProps[]>([
    {
      role: "assistant",
      content:
        "Hello! I'm the GraphiX AI assistant. I can help you understand your codebase. What would you like to know?",
      timestamp: new Date(),
    },
  ]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [codeContext, setCodeContext] = useState<CodeContext[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  // Create a new chat session when component mounts
  useEffect(() => {
    const createSession = async () => {
      if (!repositoryId && !repoUrl) return;

      try {
        const response = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions`,
          {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              Authorization: `Bearer ${localStorage.getItem("token")}`,
            },
            body: JSON.stringify({
              repository_id: repositoryId || repoUrl,
            }),
          }
        );

        if (!response.ok) {
          throw new Error(await response.text());
        }

        const data = await response.json();
        setSessionId(data.session_id);
      } catch (error) {
        toast({
          title: "Failed to create chat session",
          description:
            error instanceof Error ? error.message : "Unknown error occurred",
          variant: "destructive",
        });
      }
    };

    createSession();
  }, [repositoryId, repoUrl]);

  const handleSendMessage = async () => {
    if (!input.trim()) return;
    if (!sessionId) {
      toast({
        title: "No active session",
        description: "Please wait for the chat session to initialize",
        variant: "destructive",
      });
      return;
    }

    const userMessage: MessageProps = {
      role: "user",
      content: input,
      timestamp: new Date(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/api/chat/sessions/${sessionId}/messages`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          body: JSON.stringify({
            content: input,
          }),
        }
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();
      
      // Extract context used from the response
      const contextUsed = data.context_used || [];
      
      // Transform context items into our CodeContext format
      const newCodeContext = contextUsed.map((ctx: any) => ({
        id: ctx.id || `ctx-${Math.random().toString(36).substr(2, 9)}`,
        name: ctx.name || ctx.id?.split('/').pop() || 'Code snippet',
        type: ctx.type || 'unknown',
        file: ctx.file || 'Unknown location',
        code: ctx.content || ctx.code || '',
        line_start: ctx.line_start,
        line_end: ctx.line_end
      }));

      setCodeContext(newCodeContext);

      const assistantMessage: MessageProps = {
        role: "assistant",
        content: data.response || "I couldn't generate a proper response. Please try again.",
        timestamp: new Date(),
      };

      setMessages((prev) => [...prev, assistantMessage]);
    } catch (error) {
      toast({
        title: "Failed to send message",
        description:
          error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      });
      
      // Add error message
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: "Sorry, there was an error processing your request. Please try again.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  const handleCodeHighlight = (item: CodeContext) => {
    if (onHighlightNode) {
      // Extract the node ID from the context item
      // This will depend on how your graph nodes are identified
      const nodeId = item.id;
      onHighlightNode(nodeId);
      
      toast({
        title: "Node highlighted",
        description: `Highlighted ${item.name} in the callgraph`,
      });
    }
  };

  const handleCodeFromMessage = (code: string) => {
    // Search for the code in context or try to find a matching node
    const matchingContext = codeContext.find(ctx => 
      ctx.code.includes(code) || code.includes(ctx.code)
    );
    
    if (matchingContext && onHighlightNode) {
      onHighlightNode(matchingContext.id);
      toast({
        title: "Node highlighted",
        description: `Highlighted ${matchingContext.name} in the callgraph`,
      });
    } else {
      toast({
        title: "Cannot highlight code",
        description: "No matching node found in the callgraph",
        variant: "destructive",
      });
    }
  };

  return (
    <div className={`grid grid-cols-4 gap-4 h-full ${className}`}>
      <Card className="col-span-3 flex flex-col h-full">
        <CardHeader className="py-3">
          <CardTitle className="text-lg">Chat with GraphiX AI</CardTitle>
        </CardHeader>
        <CardContent className="flex-1 overflow-hidden p-0">
          <ScrollArea className="h-full px-4">
            <div className="space-y-4 py-4">
              {messages.map((message, index) => (
                <MessageBubble
                  key={index}
                  {...message}
                  onCodeClick={handleCodeFromMessage}
                />
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="flex gap-3">
                    <div className="rounded-lg p-4 bg-muted min-w-[50px]">
                      <div className="flex items-center gap-2">
                        <div className="h-2 w-2 rounded-full bg-primary animate-pulse"></div>
                        <div className="h-2 w-2 rounded-full bg-primary animate-pulse delay-150"></div>
                        <div className="h-2 w-2 rounded-full bg-primary animate-pulse delay-300"></div>
                      </div>
                    </div>
                  </div>
                </div>
              )}
              <div ref={messagesEndRef} />
            </div>
          </ScrollArea>
        </CardContent>
        <CardFooter className="p-4 border-t">
          <div className="flex w-full items-center space-x-2">
            <Input
              placeholder="Ask a question about your codebase..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isLoading || !sessionId}
              className="flex-1"
            />
            <Button
              size="icon"
              onClick={handleSendMessage}
              disabled={isLoading || !input.trim() || !sessionId}
            >
              {isLoading ? (
                <RefreshCw className="h-4 w-4 animate-spin" />
              ) : (
                <SendIcon className="h-4 w-4" />
              )}
            </Button>
          </div>
        </CardFooter>
      </Card>
      
      <div className="col-span-1 h-full">
        <CodeContextPanel 
          contextItems={codeContext} 
          onItemHighlight={handleCodeHighlight} 
        />
      </div>
    </div>
  );
}
