import { useState, useCallback } from "react";
interface BackendDataContent {
  nodes: any[];
  links: any[];
  metadata?: {
    framework_analyzed_as?: string;
    endpoint_runtime_seconds?: number;
    research_grade_requested?: boolean;
    status_log_from_backend?: string[];
    warning?: string;
    [key: string]: any;
  };
}
interface BackendResponse {
  status: string;
  data?: BackendDataContent;
  metrics?: {
    node_count: number;
    edge_count: number;
  };
  message?: string;
  status_log?: string[];
}
interface AnalysisDisplayResult {
  nodes: any[];
  links: any[];
  metadata?: BackendDataContent["metadata"];
  metrics?: BackendResponse["metrics"];
}
export const useCallgraphAnalysis = () => {
  const [isLoading, setIsLoading] = useState(false);
  const [status, setStatus] = useState<string>("Ready");
  const [result, setResult] = useState<AnalysisDisplayResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [statusLog, setStatusLog] = useState<string[]>([]);
  const startAnalysis = useCallback(
    async (
      repoUrl: string,
      options?: {
        researchGrade?: boolean;
        frameworkHint?: string;
        contextSensitivity?: number;
      },
    ) => {
      setIsLoading(true);
      setStatus("Initializing analysis...");
      setError(null);
      setResult(null);
      setStatusLog(["Initializing analysis..."]);
      const token = localStorage.getItem("authToken");
      if (!token) {
        setError("Authentication token not found. Please log in.");
        setIsLoading(false);
        setStatus("Error");
        return;
      }
      try {
        const response = await fetch("/api/analysis/callgraph", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
          body: JSON.stringify({
            repo_url: repoUrl,
            research_grade: options?.researchGrade || false,
            framework_hint: options?.frameworkHint || "generic",
            context_sensitivity: options?.contextSensitivity || 2,
          }),
        });
        const responseData: BackendResponse = await response.json();
        if (responseData.status_log && responseData.status_log.length > 0) {
          setStatusLog(responseData.status_log);
          setStatus(
            responseData.status_log[responseData.status_log.length - 1],
          );
        } else if (
          responseData.data?.metadata?.status_log_from_backend &&
          responseData.data.metadata.status_log_from_backend.length > 0
        ) {
          const backendStatusLog =
            responseData.data.metadata.status_log_from_backend;
          setStatusLog(backendStatusLog);
          setStatus(backendStatusLog[backendStatusLog.length - 1]);
        }
        // Handle different status responses from the server
        if (responseData.status === "processing") {
          console.log("Analysis is still processing on the backend", responseData);
          // Set a special status for processing
          setStatus("Processing - analysis is still running on the backend");
          setStatusLog(prev => [
            ...prev, 
            "The analysis is taking longer than expected but is still running.",
            "You can check back later by refreshing the page."
          ]);
          // We don't want to show an error, but we do want to let the user know it's not done yet
          setIsLoading(false);
          return;
        }
        
        if (!response.ok || responseData.status === "error") {
          const errorMessage =
            responseData.message ||
            `Analysis failed with status: ${response.status}`;
          console.error("Analysis error:", responseData);
          setError(errorMessage);
          setStatus("Error");
          setIsLoading(false);
          return;
        }

        if (responseData.status === "completed" && responseData.data) {
          // Successfully received complete analysis
          setResult({
            nodes: responseData.data.nodes,
            links: responseData.data.links,
            metadata: responseData.data.metadata,
            metrics: responseData.metrics,
          });
          setStatus("Analysis complete");
          if (responseData.data.metadata?.warning) {
            setStatus(
              `Analysis complete with warning: ${responseData.data.metadata.warning}`,
            );
          }
        } else if (responseData.data?.metadata?.status === "processing") {
          // Another way the backend might indicate processing status
          setStatus("Processing - analysis is still running on the backend");
          setStatusLog(prev => [
            ...prev, 
            "The analysis is running on the backend and taking longer than expected.",
            "Please check back in a few minutes by refreshing the page."
          ]);
          setIsLoading(false);
        } else {
          // Unexpected response format
          console.warn("Unexpected response structure:", responseData);
          setError("Received unexpected response structure from server.");
          setStatus("Error");
        }
      } catch (err) {
        console.error("Failed to start analysis:", err);
        const message =
          err instanceof Error
            ? err.message
            : "An unknown error occurred during analysis setup.";
        setError(message);
        setStatusLog((prev) => [...prev, `Error: ${message}`]);
        setStatus("Error");
      } finally {
        setIsLoading(false);
      }
    },
    [],
  );
  const reset = useCallback(() => {
    setIsLoading(false);
    setStatus("Ready");
    setError(null);
    setResult(null);
    setStatusLog([]);
  }, []);
  return {
    isLoading,
    status,
    result,
    error,
    statusLog,
    startAnalysis,
    reset,
  };
};
