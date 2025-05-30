"use client";
import React from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Button } from "@/components/ui/button";
import { ExternalLink, Eye } from "lucide-react";
import { cn } from "@/lib/utils";

export interface CodeContext {
  id: string;
  name: string;
  type: string;
  file: string;
  code: string;
  line_start?: number;
  line_end?: number;
}

interface CodeContextPanelProps {
  contextItems: CodeContext[];
  onItemHighlight: (item: CodeContext) => void;
  className?: string;
}

export default function CodeContextPanel({
  contextItems,
  onItemHighlight,
  className,
}: CodeContextPanelProps) {
  return (
    <Card className={cn("h-full flex flex-col", className)}>
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-medium">Relevant Code Context</CardTitle>
      </CardHeader>
      <CardContent className="flex-1 p-0 overflow-hidden">
        <ScrollArea className="h-full">
          {contextItems.length > 0 ? (
            <div className="space-y-3 px-4 pb-4">
              {contextItems.map((item) => (
                <div
                  key={item.id}
                  className="border rounded-md overflow-hidden bg-muted/40"
                >
                  <div className="bg-muted p-2 flex justify-between items-center">
                    <div className="truncate">
                      <span className="font-medium">{item.name}</span>
                      <span className="text-xs text-muted-foreground ml-2">
                        {item.type}
                      </span>
                    </div>
                    <div className="flex gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 px-2"
                        onClick={() => onItemHighlight(item)}
                      >
                        <Eye className="h-3.5 w-3.5 mr-1" />
                        <span className="text-xs">Highlight</span>
                      </Button>
                    </div>
                  </div>
                  <div className="text-xs p-2">
                    <div className="text-muted-foreground mb-1 truncate">
                      {item.file}
                      {item.line_start && item.line_end
                        ? ` (lines ${item.line_start}-${item.line_end})`
                        : ""}
                    </div>
                    <pre className="p-2 bg-muted rounded overflow-x-auto text-xs font-mono">
                      <code>{item.code}</code>
                    </pre>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="h-full flex items-center justify-center text-center p-4">
              <div className="text-muted-foreground">
                <p>No code context available</p>
                <p className="text-xs mt-1">
                  Context will be shown here when relevant to the conversation
                </p>
              </div>
            </div>
          )}
        </ScrollArea>
      </CardContent>
    </Card>
  );
}
