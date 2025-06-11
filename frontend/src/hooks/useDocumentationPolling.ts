// frontend/src/hooks/useDocumentationPolling.ts
import { useState, useEffect, useCallback, useRef } from 'react';
import { useToast } from '@/components/ui/use-toast';
import {
  fetchDocumentationStatus,
  DocumentationStatusResponse,
  Documentation,
} from '@/lib/analysisService';

interface UseDocumentationPollingOptions {
  pollingInterval?: number; // in milliseconds
  onSuccess?: (documentation: Documentation) => void;
  onError?: (error: Error) => void;
  onProcessing?: () => void;
}

interface UseDocumentationPollingReturn {
  documentation: Documentation | null;
  isLoading: boolean;
  error: Error | null;
  startPolling: (docId: string) => void;
  stopPolling: () => void;
  pollingStatus: 'idle' | 'polling' | 'completed' | 'failed';
}

const DEFAULT_POLLING_INTERVAL = 5000; // 5 seconds

export const useDocumentationPolling = ({
  pollingInterval = DEFAULT_POLLING_INTERVAL,
  onSuccess,
  onError,
  onProcessing,
}: UseDocumentationPollingOptions = {}): UseDocumentationPollingReturn => {
  const { toast } = useToast();
  const [documentation, setDocumentation] = useState<Documentation | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const [pollingStatus, setPollingStatus] = useState<'idle' | 'polling' | 'completed' | 'failed'>('idle');

  const intervalIdRef = useRef<NodeJS.Timeout | null>(null);
  const currentDocIdRef = useRef<string | null>(null);

  const stopPolling = useCallback(() => {
    if (intervalIdRef.current) {
      clearInterval(intervalIdRef.current);
      intervalIdRef.current = null;
    }
    setIsLoading(false);
    // Don't reset pollingStatus here, let it reflect the last known state
  }, []);

  const poll = useCallback(async (docId: string) => {
    if (currentDocIdRef.current !== docId) {
        // If docId changed, reset state before starting new poll
        setDocumentation(null);
        setError(null);
        setPollingStatus('polling');
    }
    currentDocIdRef.current = docId;
    setIsLoading(true);
    if (onProcessing) onProcessing();

    try {
      const result: DocumentationStatusResponse = await fetchDocumentationStatus(docId);
      console.log('Polling status:', result.status, 'for docId:', docId);

      if (result.status === 'completed') {
        setDocumentation(result.documentation || null);
        setPollingStatus('completed');
        setIsLoading(false);
        if (onSuccess && result.documentation) onSuccess(result.documentation);
        toast({ title: 'Documentation Ready', description: `Documentation for ${docId} has been successfully generated.`, variant: 'success' });
        stopPolling();
      } else if (result.status === 'failed') {
        const err = new Error(result.error || 'Documentation generation failed on the backend.');
        setError(err);
        setPollingStatus('failed');
        setIsLoading(false);
        if (onError) onError(err);
        toast({ title: 'Documentation Failed', description: `Failed to generate documentation for ${docId}: ${err.message}`, variant: 'destructive' });
        stopPolling();
      } else { // 'processing'
        setPollingStatus('polling');
        // Continue polling, isLoading remains true
      }
    } catch (err) {
      const pollingError = err instanceof Error ? err : new Error('Error during documentation polling');
      console.error('Error during documentation polling:', pollingError);
      setError(pollingError);
      setPollingStatus('failed');
      setIsLoading(false);
      if (onError) onError(pollingError);
      toast({ title: 'Polling Error', description: `Error polling for documentation ${docId}: ${pollingError.message}`, variant: 'destructive' });
      stopPolling();
    }
  }, [stopPolling, onSuccess, onError, onProcessing]);

  const startPolling = useCallback((docId: string) => {
    stopPolling(); // Clear any existing polling interval
    setPollingStatus('polling');
    poll(docId); // Initial immediate poll
    intervalIdRef.current = setInterval(() => poll(docId), pollingInterval);
  }, [poll, pollingInterval, stopPolling]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopPolling();
    };
  }, [stopPolling]);

  return {
    documentation,
    isLoading,
    error,
    startPolling,
    stopPolling,
    pollingStatus,
  };
};