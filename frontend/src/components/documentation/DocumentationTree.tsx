"use client";
import React, { useState } from "react";
import { Button } from "@/components/ui/button";
import { ChevronRight, ChevronDown, File, Folder } from "lucide-react";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

export interface DocTreeItem {
  id: string;
  name: string;
  type: "module" | "class" | "function" | "method" | "folder" | "file";
  children?: DocTreeItem[];
  docstring?: string;
  signature?: string;
  decorators?: string[];
  parameters?: Array<{ name: string; type?: string; description?: string }>;
  returns?: { type?: string; description?: string };
  parent_id?: string;
  complexity?: number;
}

interface DocumentationTreeProps {
  documentation: DocTreeItem[];
  onItemSelect: (item: DocTreeItem) => void;
  selectedItemId?: string;
  className?: string;
}

export default function DocumentationTree({
  documentation,
  onItemSelect,
  selectedItemId,
  className,
}: DocumentationTreeProps) {
  const [expandedItems, setExpandedItems] = useState<Set<string>>(new Set());

  const toggleExpand = (id: string) => {
    const newExpanded = new Set(expandedItems);
    if (newExpanded.has(id)) {
      newExpanded.delete(id);
    } else {
      newExpanded.add(id);
    }
    setExpandedItems(newExpanded);
  };

  const renderTreeItem = (item: DocTreeItem, depth = 0) => {
    const hasChildren = item.children && item.children.length > 0;
    const isExpanded = expandedItems.has(item.id);
    const isSelected = selectedItemId === item.id;

    return (
      <div key={item.id}>
        <div
          className={cn(
            "flex items-center py-1 px-2 rounded-md hover:bg-muted cursor-pointer",
            isSelected ? "bg-muted" : ""
          )}
          style={{ paddingLeft: `${depth * 16 + 8}px` }}
          onClick={() => onItemSelect(item)}
        >
          {hasChildren ? (
            <Button
              variant="ghost"
              size="icon"
              className="h-5 w-5 p-0 mr-1"
              onClick={(e) => {
                e.stopPropagation();
                toggleExpand(item.id);
              }}
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4" />
              ) : (
                <ChevronRight className="h-4 w-4" />
              )}
            </Button>
          ) : (
            <span className="w-6"></span>
          )}

          {item.type === "folder" ? (
            <Folder className="h-4 w-4 mr-2 text-blue-500" />
          ) : item.type === "file" ? (
            <File className="h-4 w-4 mr-2 text-gray-500" />
          ) : item.type === "class" ? (
            <div className="h-4 w-4 mr-2 rounded-sm bg-purple-500 flex items-center justify-center text-white text-[10px]">
              C
            </div>
          ) : item.type === "function" || item.type === "method" ? (
            <div className="h-4 w-4 mr-2 rounded-sm bg-green-500 flex items-center justify-center text-white text-[10px]">
              F
            </div>
          ) : (
            <div className="h-4 w-4 mr-2 rounded-sm bg-blue-500 flex items-center justify-center text-white text-[10px]">
              M
            </div>
          )}

          <span className="text-sm truncate">{item.name}</span>
          {item.complexity !== undefined && (
            <span className="ml-auto text-xs text-muted-foreground">
              {item.complexity}
            </span>
          )}
        </div>

        {hasChildren && isExpanded && (
          <div className="pl-2">
            {item.children?.map((child) => renderTreeItem(child, depth + 1))}
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={cn("h-full border rounded-md", className)}>
      <ScrollArea className="h-full p-2">
        {documentation.length > 0 ? (
          documentation.map((item) => renderTreeItem(item))
        ) : (
          <div className="p-4 text-center text-muted-foreground">
            No documentation available
          </div>
        )}
      </ScrollArea>
    </div>
  );
}
