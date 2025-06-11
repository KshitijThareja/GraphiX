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

// ... (rest of your imports)

// Interface and Component Definition
export default function ChatInterface({
  repositoryId,
  className,
  onHighlightNode,
}: ChatInterfaceProps) {
  const { repoUrl, callgraphData, documentation } = useCallgraph();
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
  const [codeContext, setCodeContext] = useState<CodeContext[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { toast } = useToast();

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  const handleSendMessage = async () => {
    if (!input.trim()) return;
    
    // Check if we have the necessary context data
    if (!callgraphData) {
      toast({
        title: "Missing callgraph data",
        description: "Please wait for the callgraph analysis to complete",
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
        `${process.env.NEXT_PUBLIC_API_URL}/analysis/chat`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${localStorage.getItem("token")}`,
          },
          body: JSON.stringify({
            query: input,
            repo_url: repoUrl,
            callgraph_data: callgraphData, // Add callgraph data as context
            documentation_data: documentation, // Add documentation data as context
          }),
        }
      );

      if (!response.ok) {
        throw new Error(await response.text());
      }

      const data = await response.json();
      
      // Extract context used from the callgraph data
      let contextUsed: CodeContext[] = [];
      
      if (callgraphData && callgraphData.nodes) {
        // Find relevant nodes based on the query and response
        const relevantNodes = callgraphData.nodes.filter((node: any) => {
          if (!node) return false;
          
          // Check if node name or docstring is mentioned in the response
          const nodeName = node.id?.split('.').pop()?.toLowerCase() || '';
          const docstring = node.metadata?.docstring?.toLowerCase() || '';
          const responseText = data.response.toLowerCase();
          const queryText = input.toLowerCase();
          
          return (
            responseText.includes(nodeName) || 
            queryText.includes(nodeName) ||
            (docstring && responseText.includes(docstring.substring(0, 15)))
          );
        }).slice(0, 5); // Limit to top 5 most relevant nodes
        
        // Convert nodes to CodeContext format
        contextUsed = relevantNodes.map((node: any) => ({
          id: node.id,
          name: node.id.split('.').pop() || 'Function',
          type: node.type || 'function',
          file: node.file || 'Unknown location',
          code: node.metadata?.code || '',
          line_start: node.line_start,
          line_end: node.line_end
        }));
      }
      
      setCodeContext(contextUsed);

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
              className="flex-1"
              disabled={!callgraphData}
            />
            <Button
              size="icon"
              onClick={handleSendMessage}
              disabled={!callgraphData || isLoading}
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