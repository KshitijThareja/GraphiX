"use client";
import {
  createContext,
  useContext,
  useState,
  ReactNode,
  useEffect,
} from "react";
interface CallgraphContextType {
  repoUrl: string;
  setRepoUrl: (url: string) => void;
  callgraphData: any;
  setCallgraphData: (data: any) => void;
  metrics: any;
  setMetrics: (metrics: any) => void;
  clearCallgraphData: () => void;
  documentation: any;
  setDocumentation: (documentation: any) => void;
}
const CallgraphContext = createContext<CallgraphContextType | undefined>(
  undefined,
);
export function CallgraphProvider({ children }: { children: ReactNode }) {
  const [repoUrl, setRepoUrl] = useState<string>(() => {
    if (typeof window !== "undefined") {
      const savedRepoUrl = localStorage.getItem("repoUrl");
      return savedRepoUrl || "";
    }
    return "";
  });
  const [callgraphData, setCallgraphData] = useState<any>(() => {
    if (typeof window !== "undefined") {
      const savedCallgraphData = localStorage.getItem("callgraphData");
      return savedCallgraphData ? JSON.parse(savedCallgraphData) : null;
    }
    return null;
  });
  const [metrics, setMetrics] = useState<any>(() => {
    if (typeof window !== "undefined") {
      const savedMetrics = localStorage.getItem("metrics");
      return savedMetrics ? JSON.parse(savedMetrics) : null;
    }
    return null;
  });
  const [documentation, setDocumentation] = useState<any>(() => {
    if (typeof window !== "undefined") {
      const savedDocumentation = localStorage.getItem("documentation");
      return savedDocumentation ? JSON.parse(savedDocumentation) : null;
    }
    return null;
  });
  useEffect(() => {
    console.log("CallgraphContext updated:", {
      repoUrl,
      callgraphData,
      metrics,
      documentation,
    });
    if (repoUrl) {
      localStorage.setItem("repoUrl", repoUrl);
    } else {
      localStorage.removeItem("repoUrl");
    }
    if (callgraphData) {
      localStorage.setItem("callgraphData", JSON.stringify(callgraphData));
    } else {
      localStorage.removeItem("callgraphData");
    }
    if (metrics) {
      localStorage.setItem("metrics", JSON.stringify(metrics));
    } else {
      localStorage.removeItem("metrics");
    }
    if (documentation) {
      localStorage.setItem("documentation", JSON.stringify(documentation));
    } else {
      localStorage.removeItem("documentation");
    }
  }, [repoUrl, callgraphData, metrics, documentation]);
  const clearCallgraphData = () => {
    setRepoUrl("");
    setCallgraphData(null);
    setMetrics(null);
    setDocumentation(null);
    localStorage.removeItem("repoUrl");
    localStorage.removeItem("callgraphData");
    localStorage.removeItem("metrics");
    localStorage.removeItem("documentation");
  };
  return (
    <CallgraphContext.Provider
      value={{
        repoUrl,
        setRepoUrl,
        callgraphData,
        setCallgraphData,
        metrics,
        setMetrics,
        clearCallgraphData,
        documentation,
        setDocumentation,
      }}
    >
      {children}
    </CallgraphContext.Provider>
  );
}
export function useCallgraph() {
  const context = useContext(CallgraphContext);
  if (!context) {
    throw new Error("useCallgraph must be used within a CallgraphProvider");
  }
  return context;
}
