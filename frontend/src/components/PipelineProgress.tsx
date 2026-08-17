import { useEffect, useState, useCallback, useRef } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  getPipelineStatus,
  retryPipeline,
  createPipelineEventStream,
  PipelineStatusResponse,
  PipelineStage,
  PipelineStageStatus,
} from "@/api/documents";

const STAGE_ORDER: PipelineStage[] = [
  "extract",
  "chunk",
  "embed",
  "ocr",
  "caption_figures",
  "dedupe",
];

const STAGE_LABELS: Record<PipelineStage, string> = {
  extract: "Extract",
  chunk: "Chunk",
  embed: "Embed",
  ocr: "OCR",
  caption_figures: "Caption Figures",
  dedupe: "Dedupe",
};

const STAGE_ICONS: Record<PipelineStage, string> = {
  extract: "📄",
  chunk: "✂️",
  embed: "🔢",
  ocr: "👁️",
  caption_figures: "🖼️",
  dedupe: "🔄",
};

const STATUS_COLORS: Record<PipelineStageStatus, string> = {
  queued: "bg-slate-100 text-slate-700",
  running: "bg-blue-100 text-blue-800 animate-pulse",
  succeeded: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  skipped: "bg-gray-100 text-gray-600",
};

const STATUS_ICONS: Record<PipelineStageStatus, string> = {
  queued: "⏳",
  running: "⏳",
  succeeded: "✅",
  failed: "❌",
  skipped: "⏭️",
};

interface PipelineProgressProps {
  orgId: string;
  documentId: string;
  initialStatus?: PipelineStatusResponse;
  onComplete?: () => void;
  onError?: (error: string) => void;
}

export function PipelineProgress({
  orgId,
  documentId,
  initialStatus,
  onComplete,
  onError,
}: PipelineProgressProps) {
  const [status, setStatus] = useState<PipelineStatusResponse | null>(initialStatus || null);
  const [isConnected, setIsConnected] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const handleMessage = useCallback((data: PipelineStatusResponse) => {
    setStatus(data);
    setIsConnected(true);

    // Check if pipeline is complete
    if (data.status === "ready") {
      cleanup();
      onComplete?.();
    } else if (data.status === "failed") {
      cleanup();
      onError?.(`Pipeline failed at stage: ${data.current_stage}`);
    }
  }, [onComplete, onError]);

  const handleError = useCallback((error: Error) => {
    console.error("SSE error:", error);
    setIsConnected(false);
    // EventSource auto-reconnects, but we can add custom logic here if needed
  }, []);

  const cleanup = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }
  }, []);

  // Establish SSE connection
  useEffect(() => {
    if (!status) {
      // Fetch initial status
      getPipelineStatus(orgId, documentId)
        .then((data) => {
          setStatus(data);
        })
        .catch((err) => {
          console.error("Failed to fetch initial pipeline status:", err);
          onError?.("Failed to load pipeline status");
        });
    }

    // Create SSE connection
    eventSourceRef.current = createPipelineEventStream(orgId, documentId, handleMessage, handleError);

    return cleanup;
  }, [orgId, documentId, status, handleMessage, handleError, cleanup, onError]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      cleanup();
    };
  }, [cleanup]);

  const handleRetry = async () => {
    if (!status || status.status !== "failed") return;

    setIsRetrying(true);
    try {
      await retryPipeline(orgId, documentId);
      // Status will be updated via SSE
    } catch (err) {
      console.error("Failed to retry pipeline:", err);
      onError?.("Failed to retry pipeline");
      setIsRetrying(false);
    }
  };

  if (!status) {
    return (
      <Card>
        <CardContent className="py-8 text-center">
          <p className="text-slate-500">Loading pipeline status...</p>
        </CardContent>
      </Card>
    );
  }

  const currentStage = status.current_stage;
  const isComplete = status.status === "ready";
  const isFailed = status.status === "failed";

  return (
    <Card>
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="font-semibold text-lg">Pipeline Progress</h3>
            <p className="text-sm text-slate-500">
              Document: {status.document_id.slice(0, 8)}...
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Badge className={STATUS_COLORS[status.pipeline_stage_status]}>
              {STATUS_ICONS[status.pipeline_stage_status]} {status.pipeline_stage_status}
            </Badge>
            {isConnected && (
              <Badge className="bg-green-100 text-green-800">Live</Badge>
            )}
          </div>
        </div>

        <div className="space-y-3">
          {STAGE_ORDER.map((stage) => {
            const stageInfo = status.stages[stage];
            const isCurrentStage = stage === currentStage;
            const isPastStage =
              stageInfo?.status === "succeeded" ||
              stageInfo?.status === "skipped";

            const stageStatus: PipelineStageStatus = stageInfo?.status || "queued";

            return (
              <div
                key={stage}
                className={`flex items-center gap-3 p-3 rounded-lg transition-all ${
                  isCurrentStage && !isComplete && !isFailed
                    ? "bg-blue-50 border border-blue-200"
                    : "bg-slate-50 border border-slate-200"
                }`}
              >
                <span className="text-xl">{STAGE_ICONS[stage]}</span>
                <div className="flex-1 min-w-0">
                  <p className="font-medium text-slate-900">{STAGE_LABELS[stage]}</p>
                  <p className="text-sm text-slate-500 truncate">
                    {stageInfo?.complete ? "Complete" : stageStatus === "running" ? "In progress..." : "Waiting"}
                  </p>
                </div>
                <Badge className={STATUS_COLORS[stageStatus]}>
                  {STATUS_ICONS[stageStatus]} {stageStatus}
                </Badge>
                {isCurrentStage && stageStatus === "running" && (
                  <div className="w-20 h-2 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-blue-500 animate-pulse"
                      style={{ width: "100%" }}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {isFailed && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded-lg">
            <p className="text-red-800 font-medium">Pipeline Failed</p>
            <p className="text-sm text-red-700 mt-1">
              Failed at stage: <strong>{current_stage || "unknown"}</strong>
            </p>
            <Button
              variant="outline"
              className="mt-2"
              onClick={handleRetry}
              disabled={isRetrying}
            >
              {isRetrying ? "Retrying..." : "Retry from Failed Stage"}
            </Button>
          </div>
        )}

        {isComplete && (
          <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-lg">
            <p className="text-green-800 font-medium">✅ Pipeline Complete</p>
            <p className="text-sm text-green-700 mt-1">
              Document is ready for search and retrieval.
            </p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}