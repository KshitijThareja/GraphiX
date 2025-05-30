"use client";
import React from "react";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { BotIcon, UserIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";

export interface MessageProps {
  role: "user" | "assistant";
  content: string;
  timestamp: Date;
  highlightTerms?: string[];
  onCodeClick?: (code: string) => void;
}

export default function MessageBubble({
  role,
  content,
  timestamp,
  highlightTerms = [],
  onCodeClick,
}: MessageProps) {
  // Function to highlight code blocks and enable click handlers
  const renderMarkdown = () => {
    return (
      <ReactMarkdown
        components={{
          code: ({ 
            inline, 
            className, 
            children, 
            ...props 
          }: any) => {
            const match = /language-(\w+)/.exec(className || "");
            if (!inline && match) {
              const codeContent = String(children).replace(/\n$/, "");
              return (
                <div className="relative group">
                  <pre
                    className={cn(
                      "px-4 py-3 rounded-md my-2 overflow-x-auto text-sm font-mono",
                      className
                    )}
                    {...props}
                  >
                    <code>{codeContent}</code>
                  </pre>
                  {onCodeClick && (
                    <button
                      className="absolute top-2 right-2 bg-primary text-primary-foreground 
                      px-2 py-1 rounded text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                      onClick={() => onCodeClick(codeContent)}
                    >
                      Highlight in Graph
                    </button>
                  )}
                </div>
              );
            }
            return (
              <code
                className={cn(
                  "px-1 py-0.5 rounded bg-muted font-mono text-sm",
                  className
                )}
                {...props}
              >
                {children}
              </code>
            );
          },
        }}
      >
        {content}
      </ReactMarkdown>
    );
  };

  return (
    <div
      className={`flex ${role === "user" ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`flex gap-3 max-w-[85%] ${
          role === "user" ? "flex-row-reverse" : ""
        }`}
      >
        <Avatar className="h-8 w-8">
          <AvatarFallback className={role === "user" ? "bg-primary" : "bg-secondary"}>
            {role === "user" ? (
              <UserIcon className="h-4 w-4" />
            ) : (
              <BotIcon className="h-4 w-4" />
            )}
          </AvatarFallback>
        </Avatar>
        <div
          className={cn(
            "rounded-lg p-4",
            role === "user"
              ? "bg-primary text-primary-foreground"
              : "bg-muted"
          )}
        >
          <div className="prose prose-sm dark:prose-invert max-w-none">
            {renderMarkdown()}
          </div>
          <p className="text-xs mt-2 opacity-70">
            {timestamp.toLocaleTimeString()}
          </p>
        </div>
      </div>
    </div>
  );
}
