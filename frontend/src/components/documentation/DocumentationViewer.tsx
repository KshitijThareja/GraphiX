"use client";
import React from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { type DocTreeItem } from "./DocumentationTree";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";

interface DocumentationViewerProps {
  selectedItem: DocTreeItem | null;
  className?: string;
}

export default function DocumentationViewer({
  selectedItem,
  className,
}: DocumentationViewerProps) {
  if (!selectedItem) {
    return (
      <div className={cn("h-full flex items-center justify-center", className)}>
        <div className="text-center p-8">
          <h3 className="text-lg font-medium">No item selected</h3>
          <p className="text-muted-foreground mt-2">
            Select an item from the documentation tree to view its details
          </p>
        </div>
      </div>
    );
  }

  return (
    <Card className={cn("h-full border flex flex-col", className)}>
      <CardHeader className="pb-2">
        <div className="flex justify-between items-start gap-2">
          <div>
            <CardTitle className="text-xl font-bold">{selectedItem.name}</CardTitle>
            <div className="flex gap-2 mt-1">
              <Badge variant="outline" className="capitalize">
                {selectedItem.type}
              </Badge>
              {selectedItem.complexity !== undefined && (
                <Badge variant="secondary">
                  Complexity: {selectedItem.complexity}
                </Badge>
              )}
            </div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="flex-1 overflow-hidden p-0">
        <Tabs defaultValue="details" className="h-full flex flex-col">
          <TabsList className="mx-6 mt-2">
            <TabsTrigger value="details">Details</TabsTrigger>
            <TabsTrigger value="docstring">Docstring</TabsTrigger>
            {selectedItem.parameters && selectedItem.parameters.length > 0 && (
              <TabsTrigger value="params">Parameters</TabsTrigger>
            )}
          </TabsList>
          <ScrollArea className="flex-1 p-6">
            <TabsContent value="details" className="m-0">
              {selectedItem.signature && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium mb-2">Signature</h3>
                  <pre className="bg-muted p-3 rounded-md overflow-x-auto text-xs">
                    {selectedItem.signature}
                  </pre>
                </div>
              )}
              {selectedItem.decorators && selectedItem.decorators.length > 0 && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium mb-2">Decorators</h3>
                  <div className="flex flex-wrap gap-2">
                    {selectedItem.decorators.map((decorator, idx) => (
                      <Badge key={idx} variant="outline">
                        {decorator}
                      </Badge>
                    ))}
                  </div>
                </div>
              )}
              {selectedItem.returns && (
                <div className="mb-4">
                  <h3 className="text-sm font-medium mb-2">Returns</h3>
                  <div className="bg-muted p-3 rounded-md">
                    <p className="text-sm">
                      <span className="font-medium">Type: </span>
                      {selectedItem.returns.type || "Not specified"}
                    </p>
                    {selectedItem.returns.description && (
                      <p className="text-sm mt-1">
                        <span className="font-medium">Description: </span>
                        {selectedItem.returns.description}
                      </p>
                    )}
                  </div>
                </div>
              )}
            </TabsContent>
            
            <TabsContent value="docstring" className="m-0">
              {selectedItem.docstring ? (
                <div className="prose prose-sm dark:prose-invert max-w-none">
                  <ReactMarkdown>{selectedItem.docstring}</ReactMarkdown>
                </div>
              ) : (
                <p className="text-muted-foreground">No docstring available</p>
              )}
            </TabsContent>
            
            <TabsContent value="params" className="m-0">
              {selectedItem.parameters && selectedItem.parameters.length > 0 ? (
                <div className="space-y-4">
                  {selectedItem.parameters.map((param, idx) => (
                    <div key={idx} className="border rounded-md p-3">
                      <h3 className="font-medium">{param.name}</h3>
                      {param.type && (
                        <p className="text-sm mt-1">
                          <span className="text-muted-foreground">Type: </span>
                          <code className="bg-muted px-1 py-0.5 rounded text-xs">
                            {param.type}
                          </code>
                        </p>
                      )}
                      {param.description && (
                        <p className="text-sm mt-2">{param.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-muted-foreground">No parameters</p>
              )}
            </TabsContent>
          </ScrollArea>
        </Tabs>
      </CardContent>
    </Card>
  );
}
