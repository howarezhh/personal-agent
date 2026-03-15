import { useCallback, useRef, useState } from 'react';

import { adaptStreamEventMetadata } from '@/adapters/chatAdapter';
import { adaptContentGenerationData } from '@/adapters/contentAdapter';
import { useSSE } from '@/hooks/useSSE';

interface RunStreamResult<TResult> {
  success: boolean;
  data?: TResult | null;
  error?: string;
}

export const useContentGenerationStream = <TResult extends Record<string, unknown>>() => {
  const { connect, cancel } = useSSE();
  const cancelledRef = useRef(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [streamingText, setStreamingText] = useState('');
  const [result, setResult] = useState<TResult | null>(null);
  const [generationId, setGenerationId] = useState<string | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const cancelStream = useCallback(() => {
    cancelledRef.current = true;
    cancel();
    setIsStreaming(false);
  }, [cancel]);

  const reset = useCallback(() => {
    cancelStream();
    setIsStreaming(false);
    setStreamingText('');
    setResult(null);
    setGenerationId(null);
    setErrorMessage(null);
  }, [cancelStream]);

  const runStream = useCallback(
    async (url: string, payload: unknown): Promise<RunStreamResult<TResult>> => {
      cancelledRef.current = false;
      setIsStreaming(true);
      setStreamingText('');
      setResult(null);
      setGenerationId(null);
      setErrorMessage(null);

      let finalResult: TResult | null = null;
      let finalError: string | undefined;

      await connect(
        `${url}${url.includes('?') ? '&' : '?'}stream=true`,
        payload,
        (event) => {
          const metadata = adaptStreamEventMetadata(event.metadata);
          if (typeof metadata.generationId === 'string') {
            setGenerationId(metadata.generationId);
          }

          if (event.type === 'content' && typeof event.content === 'string') {
            setStreamingText((current) => current + event.content);
            return;
          }

          if ((event.type === 'result' || event.type === 'done') && event.content) {
            const nextResult = adaptContentGenerationData<TResult>(event.content);
            finalResult = nextResult;
            setResult(nextResult);
            setStreamingText('');
            return;
          }

          if (event.type === 'error') {
            finalError = event.message || '流式生成失败';
            setErrorMessage(finalError);
          }
        },
        (error) => {
          finalError = error.message;
          setErrorMessage(error.message);
          setIsStreaming(false);
        },
        () => {
          setIsStreaming(false);
        }
      );

      if (cancelledRef.current) {
        return { success: false, error: '已取消生成' };
      }

      if (finalError) {
        return { success: false, error: finalError };
      }

      return { success: true, data: finalResult };
    },
    [connect]
  );

  return {
    cancel: cancelStream,
    errorMessage,
    generationId,
    isStreaming,
    reset,
    result,
    runStream,
    setResult,
    streamingText,
  };
};
