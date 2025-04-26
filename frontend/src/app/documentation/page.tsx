"use client"

import { useState } from "react"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { DownloadIcon, CopyIcon, CheckIcon } from "lucide-react"
import { useToast } from "@/components/ui/use-toast"

export default function DocumentationPage() {
  const [copied, setCopied] = useState(false)
  const { toast } = useToast()

  const handleCopy = () => {
    navigator.clipboard.writeText(sampleDocumentation)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)

    toast({
      title: "Documentation copied",
      description: "The documentation has been copied to your clipboard",
    })
  }

  const handleDownload = () => {
    const element = document.createElement("a")
    const file = new Blob([sampleDocumentation], { type: "text/markdown" })
    element.href = URL.createObjectURL(file)
    element.download = "documentation.md"
    document.body.appendChild(element)
    element.click()
    document.body.removeChild(element)

    toast({
      title: "Documentation downloaded",
      description: "The documentation has been downloaded as a Markdown file",
    })
  }

  const sampleDocumentation = `# Repository Documentation

## Overview

This repository contains a data processing application with several key components. The application follows a modular design pattern with clear separation of concerns.

## Functions

### main()

**Description**: Entry point of the application. Coordinates the overall flow by calling other functions.

**Parameters**: None

**Returns**: Exit code (0 for success, non-zero for failure)

**Dependencies**:
- process_data()
- display_output()

**Complexity**: 5

### process_data()

**Description**: Core function that handles data processing logic. It validates input, transforms data, and saves results.

**Parameters**:
- data (object): The input data to process

**Returns**: Processed data object

**Dependencies**:
- validate_input()
- transform_data()
- save_results()
- log_error()

**Complexity**: 8

### validate_input()

**Description**: Validates the input data against a schema to ensure it meets requirements.

**Parameters**:
- input (object): The input data to validate

**Returns**: Boolean indicating validity

**Dependencies**: None

**Complexity**: 3

### transform_data()

**Description**: Applies transformations to the validated data.

**Parameters**:
- data (object): The validated data to transform

**Returns**: Transformed data object

**Dependencies**:
- log_error()

**Complexity**: 7

### save_results()

**Description**: Persists the processed data to storage.

**Parameters**:
- results (object): The processed data to save

**Returns**: Boolean indicating success

**Dependencies**:
- log_error()

**Complexity**: 4

### log_error()

**Description**: Handles error logging throughout the application.

**Parameters**:
- message (string): Error message
- level (string, optional): Error severity level

**Returns**: None

**Dependencies**: None

**Complexity**: 2

### display_output()

**Description**: Renders the processed data for user viewing.

**Parameters**:
- data (object): The processed data to display

**Returns**: None

**Dependencies**: None

**Complexity**: 6

## Architecture

The application follows a linear processing flow:
1. Main entry point coordinates the process
2. Input data is validated
3. Valid data is transformed
4. Results are saved
5. Output is displayed to the user

Error handling is implemented throughout the process with the log_error function.

## Recommendations

Based on the callgraph analysis:

1. The process_data function has high complexity (8) and multiple dependencies. Consider refactoring into smaller, more focused functions.

2. The transform_data function also has relatively high complexity (7). Look for opportunities to break it down into simpler transformations.

3. Error handling is centralized through log_error, which is a good practice. Consider expanding with different severity levels.

4. The application has a clear flow but could benefit from more modular architecture, possibly introducing a service layer.`

  return (
    <div className="container py-12">
      <h1 className="text-3xl font-bold mb-6">Automated Documentation</h1>

      <Card>
        <CardHeader>
          <CardTitle>Repository Documentation</CardTitle>
          <CardDescription>Automatically generated documentation for your codebase</CardDescription>
        </CardHeader>
        <CardContent>
          <Tabs defaultValue="markdown" className="w-full">
            <TabsList className="grid w-full grid-cols-2">
              <TabsTrigger value="markdown">Markdown</TabsTrigger>
              <TabsTrigger value="preview">Preview</TabsTrigger>
            </TabsList>
            <TabsContent value="markdown" className="mt-4">
              <div className="relative">
                <pre className="bg-muted p-4 rounded-lg overflow-auto max-h-[600px] text-sm">
                  <code>{sampleDocumentation}</code>
                </pre>
                <div className="absolute top-2 right-2 flex gap-2">
                  <Button variant="outline" size="icon" onClick={handleCopy} className="h-8 w-8">
                    {copied ? <CheckIcon className="h-4 w-4" /> : <CopyIcon className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
            </TabsContent>
            <TabsContent value="preview" className="mt-4">
              <div className="bg-background border rounded-lg p-6 overflow-auto max-h-[600px]">
                <h1 className="text-2xl font-bold mb-4">Repository Documentation</h1>

                <h2 className="text-xl font-semibold mt-6 mb-3">Overview</h2>
                <p className="mb-4">
                  This repository contains a data processing application with several key components. The application
                  follows a modular design pattern with clear separation of concerns.
                </p>

                <h2 className="text-xl font-semibold mt-6 mb-3">Functions</h2>

                <div className="mb-6">
                  <h3 className="text-lg font-medium mb-2">main()</h3>
                  <p className="mb-2">
                    <strong>Description</strong>: Entry point of the application. Coordinates the overall flow by
                    calling other functions.
                  </p>
                  <p className="mb-2">
                    <strong>Parameters</strong>: None
                  </p>
                  <p className="mb-2">
                    <strong>Returns</strong>: Exit code (0 for success, non-zero for failure)
                  </p>
                  <p className="mb-2">
                    <strong>Dependencies</strong>:
                  </p>
                  <ul className="list-disc pl-6 mb-2">
                    <li>process_data()</li>
                    <li>display_output()</li>
                  </ul>
                  <p>
                    <strong>Complexity</strong>: 5
                  </p>
                </div>

                <div className="mb-6">
                  <h3 className="text-lg font-medium mb-2">process_data()</h3>
                  <p className="mb-2">
                    <strong>Description</strong>: Core function that handles data processing logic. It validates input,
                    transforms data, and saves results.
                  </p>
                  <p className="mb-2">
                    <strong>Parameters</strong>:
                  </p>
                  <ul className="list-disc pl-6 mb-2">
                    <li>data (object): The input data to process</li>
                  </ul>
                  <p className="mb-2">
                    <strong>Returns</strong>: Processed data object
                  </p>
                  <p className="mb-2">
                    <strong>Dependencies</strong>:
                  </p>
                  <ul className="list-disc pl-6 mb-2">
                    <li>validate_input()</li>
                    <li>transform_data()</li>
                    <li>save_results()</li>
                    <li>log_error()</li>
                  </ul>
                  <p>
                    <strong>Complexity</strong>: 8
                  </p>
                </div>

                {/* More functions would be rendered here */}

                <h2 className="text-xl font-semibold mt-6 mb-3">Architecture</h2>
                <p className="mb-2">The application follows a linear processing flow:</p>
                <ol className="list-decimal pl-6 mb-4">
                  <li>Main entry point coordinates the process</li>
                  <li>Input data is validated</li>
                  <li>Valid data is transformed</li>
                  <li>Results are saved</li>
                  <li>Output is displayed to the user</li>
                </ol>
                <p>Error handling is implemented throughout the process with the log_error function.</p>

                <h2 className="text-xl font-semibold mt-6 mb-3">Recommendations</h2>
                <ol className="list-decimal pl-6">
                  <li className="mb-2">
                    The process_data function has high complexity (8) and multiple dependencies. Consider refactoring
                    into smaller, more focused functions.
                  </li>
                  <li className="mb-2">
                    The transform_data function also has relatively high complexity (7). Look for opportunities to break
                    it down into simpler transformations.
                  </li>
                  <li className="mb-2">
                    Error handling is centralized through log_error, which is a good practice. Consider expanding with
                    different severity levels.
                  </li>
                  <li>
                    The application has a clear flow but could benefit from more modular architecture, possibly
                    introducing a service layer.
                  </li>
                </ol>
              </div>
            </TabsContent>
          </Tabs>
        </CardContent>
        <CardFooter className="flex justify-end gap-2">
          <Button variant="outline" onClick={handleCopy}>
            <CopyIcon className="h-4 w-4 mr-2" />
            Copy
          </Button>
          <Button onClick={handleDownload}>
            <DownloadIcon className="h-4 w-4 mr-2" />
            Download
          </Button>
        </CardFooter>
      </Card>
    </div>
  )
}
