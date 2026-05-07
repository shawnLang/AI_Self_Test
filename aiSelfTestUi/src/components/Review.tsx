import React, { useMemo, useState } from 'react';
import { Check, List, LayoutGrid, Image as ImageIcon, CheckSquare, ChevronLeft, ChevronRight, SkipForward, UploadCloud, Save, Maximize2, Minimize2 } from 'lucide-react';
import {
  confirmReviewItems,
  skipReviewItems,
  submitTaskItem,
  submitTaskReviewItems,
  updateTaskItemReviewRow,
  type TaskItemDataStatus,
  type ReviewItem,
  type ReviewRow,
  type VideoDatajsonDetection,
  type VideoDatajsonPayload,
} from '../api/taskItems';
import {
  useCompletedReviewTasks,
  useInvalidateReviews,
  useReviews,
} from '../hooks/useReviewQueries';
import {
  getReviewRows,
  isResultMatched,
  useReviewItem,
  type ConsistencyFilter,
} from '../hooks/useReviewItem';

const reviewStatusOptions: TaskItemDataStatus[] = ['默认', '新增', '修改', '删除'];
type RowDraft = { status: string; aiName: string };
type ReviewConfirmFilter = 'all' | 'pending' | 'confirmed' | 'skipped';
type VideoOverlayDetection = {
  frameIndex: number;
  trackId: string;
  bbox: [number, number, number, number];
  score: number;
};
type IndexedVideoDetections = {
  byFrame: Map<number, VideoOverlayDetection[]>;
  sourceFrameCount: number;
};

const BBOX_COLORS: Record<string, string> = {
  keep: 'border-green-400',
  add: 'border-blue-400',
  rename: 'border-amber-400',
  exclude: 'border-gray-400',
  error: 'border-red-400',
};
const BBOX_LABEL_COLORS: Record<string, string> = {
  keep: 'bg-green-500',
  add: 'bg-blue-500',
  rename: 'bg-amber-500',
  exclude: 'bg-gray-500',
  error: 'bg-red-500',
};

function parseVideoDatajson(payload: unknown): IndexedVideoDetections {
  const frames = Array.isArray(payload) ? payload as VideoDatajsonPayload : [];
  const byFrame = new Map<number, VideoOverlayDetection[]>();

  frames.forEach((framePayload, fallbackIndex) => {
    if (!Array.isArray(framePayload)) return;
    const frameDetections: VideoOverlayDetection[] = [];
    framePayload.forEach((rawDetection) => {
      const detection = parseVideoDetection(rawDetection, fallbackIndex);
      if (!detection) return;
      frameDetections.push(detection);
      const indexedDetections = byFrame.get(detection.frameIndex) ?? [];
      indexedDetections.push(detection);
      byFrame.set(detection.frameIndex, indexedDetections);
    });
    if (frameDetections.length > 0) {
      byFrame.set(fallbackIndex, frameDetections);
    }
  });

  return { byFrame, sourceFrameCount: frames.length };
}

function parseVideoDetection(
  detection: VideoDatajsonDetection,
  fallbackIndex: number,
): VideoOverlayDetection | null {
  if (!detection || typeof detection !== 'object') return null;
  const bbox = Array.isArray(detection.bbox) ? detection.bbox : [];
  if (bbox.length !== 4) return null;

  const trackId = String(detection.trackId ?? '').trim();
  if (!trackId) return null;

  const frameIndex = Number(detection.index ?? fallbackIndex);
  const score = Number(detection.score ?? 0);
  const parsedBbox = bbox.map((value) => Number(value));
  if (!Number.isFinite(frameIndex) || parsedBbox.some((value) => !Number.isFinite(value))) {
    return null;
  }
  if (parsedBbox[2] <= parsedBbox[0] || parsedBbox[3] <= parsedBbox[1]) {
    return null;
  }

  return {
    frameIndex: Math.round(frameIndex),
    trackId,
    bbox: [parsedBbox[0], parsedBbox[1], parsedBbox[2], parsedBbox[3]],
    score: Number.isFinite(score) ? score : 0,
  };
}

function findNearestFrameIndex(frameIndexes: number[], frameIndex: number): number | null {
  if (frameIndexes.length === 0) return null;

  let lastFrameIndex = frameIndexes[0];
  for (const nextFrameIndex of frameIndexes) {
    if (nextFrameIndex === frameIndex) return nextFrameIndex;
    if (nextFrameIndex > frameIndex) {
      return Math.abs(nextFrameIndex - frameIndex) < Math.abs(frameIndex - lastFrameIndex)
        ? nextFrameIndex
        : lastFrameIndex;
    }
    if (lastFrameIndex <= frameIndex) {
      lastFrameIndex = nextFrameIndex;
    }
  }
  return lastFrameIndex;
}

function findVisibleDetections(
  detectionsByFrame: IndexedVideoDetections,
  frameIndexes: number[],
  frameIndex: number,
  rowsByTrackId: Map<string, ReviewRow>,
): VideoOverlayDetection[] {
  const nearestFrameIndex = findNearestFrameIndex(frameIndexes, frameIndex);
  if (nearestFrameIndex === null) return [];

  const trackIdSet = new Set(rowsByTrackId.keys());
  return (detectionsByFrame.byFrame.get(nearestFrameIndex) ?? []).filter((detection) => (
    trackIdSet.has(String(detection.trackId))
  ));
}

function getRowsByTrackId(rows: ReviewRow[]): Map<string, ReviewRow> {
  const rowsByTrackId = new Map<string, ReviewRow>();
  rows.forEach((row) => {
    String(row.trackIds || '')
      .split(',')
      .map((part) => part.trim())
      .filter(Boolean)
      .forEach((trackId) => rowsByTrackId.set(trackId, row));
  });
  return rowsByTrackId;
}

function VideoWithDatajsonOverlay({ item, className }: { item: ReviewItem; className: string }) {
  const videoRef = React.useRef<HTMLVideoElement | null>(null);
  const wrapperRef = React.useRef<HTMLDivElement | null>(null);
  const [detectionsByFrame, setDetectionsByFrame] = React.useState<IndexedVideoDetections>({
    byFrame: new Map(),
    sourceFrameCount: 0,
  });
  const [currentFrameIndex, setCurrentFrameIndex] = React.useState(0);
  const [videoBox, setVideoBox] = React.useState({ width: 0, height: 0, left: 0, top: 0 });
  const [loadState, setLoadState] = React.useState<'idle' | 'loading' | 'ready' | 'failed'>('idle');
  const [isFullscreen, setIsFullscreen] = React.useState(false);

  React.useEffect(() => {
    if (!item.resultFileUrl) {
      setDetectionsByFrame({ byFrame: new Map(), sourceFrameCount: 0 });
      setLoadState('idle');
      return;
    }

    let cancelled = false;
    setLoadState('loading');
    fetch(item.resultFileUrl)
      .then((response) => {
        if (!response.ok) throw new Error(`datajson load failed: ${response.status}`);
        return response.json();
      })
      .then((payload) => {
        if (cancelled) return;
        setDetectionsByFrame(parseVideoDatajson(payload));
        setLoadState('ready');
      })
      .catch((error) => {
        console.error(error);
        if (cancelled) return;
        setDetectionsByFrame({ byFrame: new Map(), sourceFrameCount: 0 });
        setLoadState('failed');
      });

    return () => {
      cancelled = true;
    };
  }, [item.resultFileUrl]);

  React.useEffect(() => {
    const video = videoRef.current;
    const wrapper = wrapperRef.current;
    if (!video || !wrapper) return;

    let frameId = 0;
    const update = () => {
      const maxFrameIndex = detectionsByFrame.sourceFrameCount > 0
        ? detectionsByFrame.sourceFrameCount - 1
        : detectionsByFrame.byFrame.size > 0 ? Math.max(...detectionsByFrame.byFrame.keys()) : 0;
      const estimatedFps = video.duration > 0 && maxFrameIndex > 0 ? (maxFrameIndex + 1) / video.duration : 0;
      setCurrentFrameIndex(estimatedFps > 0 ? Math.round(video.currentTime * estimatedFps) : 0);

      const wrapperWidth = wrapper.clientWidth;
      const wrapperHeight = wrapper.clientHeight;
      const videoWidth = video.videoWidth;
      const videoHeight = video.videoHeight;
      if (wrapperWidth > 0 && wrapperHeight > 0 && videoWidth > 0 && videoHeight > 0) {
        const scale = Math.min(wrapperWidth / videoWidth, wrapperHeight / videoHeight);
        const renderedWidth = videoWidth * scale;
        const renderedHeight = videoHeight * scale;
        setVideoBox({
          width: renderedWidth,
          height: renderedHeight,
          left: (wrapperWidth - renderedWidth) / 2,
          top: (wrapperHeight - renderedHeight) / 2,
        });
      }

      frameId = window.requestAnimationFrame(update);
    };

    frameId = window.requestAnimationFrame(update);
    return () => window.cancelAnimationFrame(frameId);
  }, [detectionsByFrame]);

  React.useEffect(() => {
    const handleFullscreenChange = () => {
      setIsFullscreen(document.fullscreenElement === wrapperRef.current);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const toggleFullscreen = async () => {
    if (document.fullscreenElement === wrapperRef.current) {
      await document.exitFullscreen();
      return;
    }
    await wrapperRef.current?.requestFullscreen();
  };

  const rowsByTrackId = React.useMemo(() => getRowsByTrackId(item.reviewRows), [item.reviewRows]);
  const frameIndexes = React.useMemo(
    () => [...detectionsByFrame.byFrame.keys()].sort((left, right) => left - right),
    [detectionsByFrame],
  );
  const visibleDetections = findVisibleDetections(
    detectionsByFrame,
    frameIndexes,
    currentFrameIndex,
    rowsByTrackId,
  );

  return (
    <div ref={wrapperRef} className={`relative overflow-hidden bg-black ${className}`}>
      <video
        ref={videoRef}
        src={item.mediaUrl || item.imageUrl}
        className="h-full w-full object-contain"
        controls
        muted
        playsInline
        preload="metadata"
        controlsList="nofullscreen"
      />
      <div className="pointer-events-none absolute inset-0">
        {visibleDetections.map((detection, index) => {
          const row = rowsByTrackId.get(detection.trackId);
          if (!row || videoBox.width <= 0 || videoBox.height <= 0) return null;
          const video = videoRef.current;
          if (!video || video.videoWidth <= 0 || video.videoHeight <= 0) return null;

          const [minx, miny, maxx, maxy] = detection.bbox;
          const left = videoBox.left + (minx / video.videoWidth) * videoBox.width;
          const top = videoBox.top + (miny / video.videoHeight) * videoBox.height;
          const width = ((maxx - minx) / video.videoWidth) * videoBox.width;
          const height = ((maxy - miny) / video.videoHeight) * videoBox.height;
          const borderClass = BBOX_COLORS[row.decision] ?? 'border-blue-400';
          const labelClass = BBOX_LABEL_COLORS[row.decision] ?? 'bg-blue-500';

          return (
            <div
              key={`${detection.frameIndex}-${detection.trackId}-${index}`}
              className={`absolute border-2 ${borderClass}`}
              style={{ left, top, width, height }}
              title={`${row.originalName || '--'} ${detection.score ? detection.score.toFixed(2) : ''}`}
            >
              <span className={`absolute -top-4 left-0 ${labelClass} text-white text-[10px] font-bold px-1 leading-4 rounded-sm`}>
                {index + 1}
              </span>
            </div>
          );
        })}
      </div>
      {loadState === 'failed' && (
        <div className="pointer-events-none absolute bottom-2 right-2 rounded bg-black/65 px-2 py-1 text-[11px] text-white">
          未加载轨迹数据
        </div>
      )}
      <button
        type="button"
        onClick={toggleFullscreen}
        className="absolute right-2 top-2 z-10 inline-flex h-8 w-8 items-center justify-center rounded bg-black/65 text-white transition-colors hover:bg-black/80"
        aria-label={isFullscreen ? '退出全屏' : '全屏'}
        title={isFullscreen ? '退出全屏' : '全屏'}
      >
        {isFullscreen ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
      </button>
    </div>
  );
}

export default function Review({ initialTaskId = null }: { initialTaskId?: number | null }) {
  const [viewMode, setViewMode] = useState<'list' | 'grid' | 'gallery'>('grid');
  const [activeItemId, setActiveItemId] = useState<string | null>(null);
  const [selectedTaskId, setSelectedTaskId] = useState<string>(initialTaskId ? String(initialTaskId) : '');
  const [consistencyFilter, setConsistencyFilter] = useState<ConsistencyFilter>('all');
  const [confirmFilter, setConfirmFilter] = useState<ReviewConfirmFilter>('all');
  const [previewItem, setPreviewItem] = useState<ReviewItem | null>(null);
  const [selectedItemIds, setSelectedItemIds] = useState<string[]>([]);
  const [rowDrafts, setRowDrafts] = useState<Record<string, RowDraft>>({});
  const { data: taskOptions = [] } = useCompletedReviewTasks();
  const { data: items = [] } = useReviews(selectedTaskId);
  const { invalidateTasks, invalidateReviews } = useInvalidateReviews();

  React.useEffect(() => {
    if (Array.isArray(taskOptions) && taskOptions.length > 0) {
      const initialId = initialTaskId ? String(initialTaskId) : '';
      const hasInitial = initialId ? taskOptions.some((task) => String(task.id) === initialId) : false;
      setSelectedTaskId((current) => {
        if (current && taskOptions.some((task) => String(task.id) === current)) return current;
        if (hasInitial) return initialId;
        return String(taskOptions[0].id);
      });
    } else {
      setSelectedTaskId('');
    }
    setSelectedItemIds([]);
  }, [taskOptions, initialTaskId]);

  const invalidateCurrentReview = async () => {
    await invalidateReviews(selectedTaskId);
    await invalidateTasks();
  };

  const handleBatchResult = (data: any, label: string) => {
    if (Number(data.failureCount || 0) > 0) {
      window.alert(`${label}完成：成功 ${Number(data.successCount || 0)} 条，失败 ${Number(data.failureCount || 0)} 条。`);
    }
  };

  const handleConfirm = async (id: string) => {
    try {
      const data = await confirmReviewItems([id]);
      handleBatchResult(data, '确认');
      setSelectedItemIds((current) => current.filter((itemId) => itemId !== id));
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  const handleSkip = async (id: string) => {
    try {
      const data = await skipReviewItems([id]);
      handleBatchResult(data, '跳过');
      setSelectedItemIds((current) => current.filter((itemId) => itemId !== id));
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  const handleSubmit = async (id: string) => {
    try {
      await submitTaskItem(Number(id));
      setSelectedItemIds((current) => current.filter((itemId) => itemId !== id));
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  const handleBatchConfirm = async () => {
    if (!selectedConfirmableIds.length) return;
    try {
      const data = await confirmReviewItems(selectedConfirmableIds);
      handleBatchResult(data, '批量确认');
      setSelectedItemIds([]);
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  const handleBatchSkip = async () => {
    if (!selectedSkippableIds.length) return;
    if (!window.confirm('确定要批量跳过选中的待复核项吗？')) return;
    try {
      const data = await skipReviewItems(selectedSkippableIds);
      handleBatchResult(data, '批量跳过');
      setSelectedItemIds([]);
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  const handleBatchSubmit = async () => {
    if (!selectedTaskId || taskSubmittableIds.length === 0) return;
    try {
      const data = await submitTaskReviewItems(Number(selectedTaskId));
      handleBatchResult(data, '批量提交远端');
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  const openPreview = (item: ReviewItem) => {
    setPreviewItem(item);
  };

  const closePreview = () => {
    setPreviewItem(null);
  };

  const {
    filteredItems: consistencyFilteredItems,
    matchedCount,
    mismatchedCount,
    totalCount,
  } = useReviewItem(items, consistencyFilter);
  const pendingConfirmCount = consistencyFilteredItems.filter((item) => item.confirmState === '待确认').length;
  const confirmedCount = consistencyFilteredItems.filter((item) => item.confirmState === '已确认').length;
  const skippedCount = consistencyFilteredItems.filter((item) => item.confirmState === '已跳过').length;
  const filteredItems = useMemo(
    () => consistencyFilteredItems.filter((item) => {
      if (confirmFilter === 'pending') return item.confirmState === '待确认';
      if (confirmFilter === 'confirmed') return item.confirmState === '已确认';
      if (confirmFilter === 'skipped') return item.confirmState === '已跳过';
      return true;
    }),
    [consistencyFilteredItems, confirmFilter],
  );

  const isConfirmable = (item: ReviewItem) => item.confirmState === '待确认' && !isResultMatched(item);
  const isSkippable = (item: ReviewItem) => item.confirmState === '待确认' && !isResultMatched(item);
  const isSubmittable = (item: ReviewItem) => item.confirmState === '已确认'
    && ['待提交', '提交失败'].includes(item.remoteState || '');
  const isSelectable = (item: ReviewItem) => isConfirmable(item) || isSkippable(item) || isSubmittable(item);
  const isRowEditable = (item: ReviewItem) => !['已完成'].includes(item.status || '')
    && !['已提交'].includes(item.remoteState || '');

  const selectedItems = useMemo(
    () => items.filter((item) => selectedItemIds.includes(String(item.id))),
    [items, selectedItemIds],
  );
  const selectedConfirmableIds = selectedItems.filter(isConfirmable).map((item) => String(item.id));
  const selectedSkippableIds = selectedItems.filter(isSkippable).map((item) => String(item.id));
  const taskSubmittableIds = items.filter(isSubmittable).map((item) => String(item.id));

  const toggleItemSelection = (id: string) => {
    setSelectedItemIds((current) => current.includes(id)
      ? current.filter((itemId) => itemId !== id)
      : [...current, id]);
  };

  const selectCurrentProcessableItems = () => {
    setSelectedItemIds(filteredItems.filter(isSelectable).map((item) => String(item.id)));
  };

  const clearSelection = () => {
    setSelectedItemIds([]);
  };

  const getRowDraft = (row: any): RowDraft => {
    const key = String(row.recordId);
    return rowDrafts[key] ?? { status: row.sourceStatus || '默认', aiName: row.aiName || '' };
  };

  const setRowDraft = (row: any, patch: Partial<RowDraft>) => {
    const key = String(row.recordId);
    setRowDrafts((current) => ({
      ...current,
      [key]: { ...getRowDraft(row), ...patch },
    }));
  };

  const handleSaveRow = async (item: ReviewItem, row: any) => {
    const draft = getRowDraft(row);
    try {
      await updateTaskItemReviewRow({
        task_item_id: item.id,
        task_item_data_id: Number(row.recordId),
        status: draft.status,
        llm_name: draft.aiName.trim() || null,
      });
      setRowDrafts((current) => {
        const next = { ...current };
        delete next[String(row.recordId)];
        return next;
      });
      await invalidateCurrentReview();
    } catch (e) { console.error(e); }
  };

  React.useEffect(() => {
    if (filteredItems.length === 0) {
      setActiveItemId(null);
      return;
    }

    const stillExists = filteredItems.some((item) => String(item.id) === activeItemId);
    if (!stillExists) {
      setActiveItemId(String(filteredItems[0].id));
    }
  }, [filteredItems, activeItemId]);

  React.useEffect(() => {
    const validIds = new Set(items.map((item) => String(item.id)));
    setSelectedItemIds((current) => current.filter((id) => validIds.has(id)));
  }, [items]);

  const getActiveIndex = () => filteredItems.findIndex((item) => String(item.id) === activeItemId);

  const switchGalleryItem = (direction: 'prev' | 'next') => {
    if (filteredItems.length <= 1) return;

    const currentIndex = getActiveIndex();
    const safeIndex = currentIndex >= 0 ? currentIndex : 0;
    const nextIndex = direction === 'prev'
      ? Math.max(0, safeIndex - 1)
      : Math.min(filteredItems.length - 1, safeIndex + 1);

    if (nextIndex !== safeIndex) {
      setActiveItemId(String(filteredItems[nextIndex].id));
    }
  };

  React.useEffect(() => {
    if (viewMode !== 'gallery' || filteredItems.length <= 1 || previewItem) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const tagName = target?.tagName;
      const isEditable = target?.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(tagName || '');
      if (isEditable) return;

      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        switchGalleryItem('prev');
      }

      if (event.key === 'ArrowRight') {
        event.preventDefault();
        switchGalleryItem('next');
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [viewMode, filteredItems, activeItemId, previewItem]);

  const renderVideoWithBboxOverlay = (item: ReviewItem, className: string) => (
    <VideoWithDatajsonOverlay item={item} className={className} />
  );

  const renderMedia = (item: ReviewItem, className: string) => {
    if (item.mediaType === 'video') {
      return renderVideoWithBboxOverlay(item, className);
    }
    return <img src={item.imageUrl} alt="Thumbnail" className={className} referrerPolicy="no-referrer" />;
  };

  const renderImageWithBboxOverlay = (item: any, options?: { contain?: boolean }) => {
    const rows = Array.isArray(item.reviewRows) ? item.reviewRows : [];
    const validRows = rows.filter((row: any) => {
      const b = row.bbox;
      const s = row.groundingMeta?.sourceSize;
      return b && s && s.width > 0 && s.height > 0 && b.maxx > b.minx && b.maxy > b.miny;
    });

    const renderBboxes = (rows: any[]) => rows.flatMap((row: any, index: number) => {
      const b = row.bbox;
      const s = row.groundingMeta.sourceSize;
      const borderClass = BBOX_COLORS[row.decision] ?? 'border-blue-400';
      const labelClass = BBOX_LABEL_COLORS[row.decision] ?? 'bg-blue-500';
      const toPercent = (box: any) => ({
        left: (box.minx / s.width) * 100,
        top: (box.miny / s.height) * 100,
        width: ((box.maxx - box.minx) / s.width) * 100,
        height: ((box.maxy - box.miny) / s.height) * 100,
      });
      const orig = toPercent(b);
      const elems = [
        <div
          key={`bbox-${index}`}
          className={`absolute border-2 ${borderClass} pointer-events-none`}
          style={{ left: `${orig.left}%`, top: `${orig.top}%`, width: `${orig.width}%`, height: `${orig.height}%` }}
        >
          <span className={`absolute -top-4 left-0 ${labelClass} text-white text-[10px] font-bold px-1 leading-4 rounded-sm`}>
            {index + 1}
          </span>
        </div>
      ];
      const cropBox = row.groundingMeta?.cropBox;
      if (cropBox && cropBox.maxx > cropBox.minx && cropBox.maxy > cropBox.miny) {
        const crop = toPercent(cropBox);
        elems.push(
          <div
            key={`crop-${index}`}
            className={`absolute border-2 border-dashed ${borderClass} pointer-events-none opacity-60`}
            style={{ left: `${crop.left}%`, top: `${crop.top}%`, width: `${crop.width}%`, height: `${crop.height}%` }}
          />
        );
      }
      return elems;
    });

    if (options?.contain) {
      // 用 aspect-ratio wrapper 使图片精确填满自身比例，bbox % 坐标在 wrapper 内完全准确
      const sourceSize = validRows[0]?.groundingMeta?.sourceSize;
      const aspectRatio = sourceSize ? `${sourceSize.width}/${sourceSize.height}` : undefined;
      return (
        <div className="w-full h-full flex items-center justify-center overflow-hidden">
          <div
            className="relative"
            style={aspectRatio ? { aspectRatio, maxWidth: '100%', maxHeight: '100%' } : { width: '100%', height: '100%' }}
          >
            <img src={item.imageUrl} alt="Thumbnail" className="w-full h-full object-cover" referrerPolicy="no-referrer" />
            {renderBboxes(validRows)}
          </div>
        </div>
      );
    }

    // 自然模式：图片以原始宽高比伸展，bbox % 坐标完全对齐
    return (
      <div className="relative w-full">
        <img src={item.imageUrl} alt="Thumbnail" className="w-full h-auto block" referrerPolicy="no-referrer" />
        {renderBboxes(validRows)}
      </div>
    );
  };

  const getDecisionLabel = (row: any) => {
    if (row.sourceStatus) return row.sourceStatus;
    if (row.decision === 'keep') return '保留';
    if (row.decision === 'add') return '新增';
    if (row.decision === 'rename') return '改名';
    if (row.decision === 'exclude') return '排除';
    return '错误';
  };

  const getDecisionClass = (row: any) => {
    if (row.sourceStatus === '新增') return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300';
    if (row.sourceStatus === '修改') return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
    if (row.sourceStatus === '删除') return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300';
    if (row.sourceStatus === '默认') return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300';
    if (row.decision === 'keep') return 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300';
    if (row.decision === 'add') return 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300';
    if (row.decision === 'rename') return 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300';
    if (row.decision === 'exclude') return 'bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300';
    return 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300';
  };

  const renderSummaryBadges = (item: any) => (
    <div className="flex flex-wrap gap-2 text-xs">
      <span className="rounded-full bg-blue-50 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300 px-2 py-1">
        待提交 {Number(item.submitCount || 0)} 条
      </span>
      <span className="rounded-full bg-gray-100 text-gray-700 dark:bg-gray-700 dark:text-gray-300 px-2 py-1">
        排除 {Number(item.excludedCount || 0)} 条
      </span>
      {item.willSubmitEmptyArray && (
        <span className="rounded-full bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300 px-2 py-1">
          无待提交差异
        </span>
      )}
      {item.remoteError && (
        <span className="rounded-full bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300 px-2 py-1">
          远端提交失败/可重试
        </span>
      )}
    </div>
  );

  const renderSelectionCheckbox = (item: ReviewItem) => {
    const id = String(item.id);
    const selectable = isSelectable(item);

    return (
      <input
        type="checkbox"
        aria-label={`选择复核项 ${id}`}
        checked={selectedItemIds.includes(id)}
        disabled={!selectable}
        onChange={() => toggleItemSelection(id)}
        className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500 disabled:opacity-40"
      />
    );
  };

  const renderStatusPill = (item: ReviewItem) => {
    if (item.status === '已完成' || item.remoteState === '已提交') {
      return '已提交';
    }
    if (item.confirmState === '已跳过') {
      return isResultMatched(item) ? '自动跳过' : '已跳过';
    }
    if (item.confirmState === '已确认') {
      return item.remoteState === '提交失败' ? '待重试提交' : '待提交远端';
    }
    return '待复核';
  };

  const renderItemActions = (item: ReviewItem, block = false) => {
    const layoutClass = block ? 'flex flex-col gap-2' : 'flex flex-wrap justify-end gap-2';
    const buttonClass = block
      ? 'w-full justify-center'
      : 'justify-center';

    return (
      <div className={layoutClass}>
        {isConfirmable(item) && (
          <button
            type="button"
            onClick={() => handleConfirm(String(item.id))}
            className={`${buttonClass} inline-flex items-center gap-2 rounded-lg bg-blue-600 px-3 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors`}
          >
            <Check className="w-4 h-4" />
            确认
          </button>
        )}
        {isSkippable(item) && (
          <button
            type="button"
            onClick={() => handleSkip(String(item.id))}
            className={`${buttonClass} inline-flex items-center gap-2 rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-300 dark:hover:bg-gray-700 transition-colors`}
          >
            <SkipForward className="w-4 h-4" />
            跳过
          </button>
        )}
        {isSubmittable(item) && (
          <button
            type="button"
            onClick={() => handleSubmit(String(item.id))}
            className={`${buttonClass} inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-3 py-2 text-sm font-medium text-white hover:bg-emerald-700 transition-colors`}
          >
            <UploadCloud className="w-4 h-4" />
            {item.remoteState === '提交失败' ? '重试提交远端' : '提交远端'}
          </button>
        )}
        {!isSelectable(item) && (
          <span className="inline-flex items-center justify-center rounded-lg bg-gray-100 px-3 py-2 text-sm font-medium text-gray-600 dark:bg-gray-700 dark:text-gray-300">
            {renderStatusPill(item)}
          </span>
        )}
      </div>
    );
  };

  const renderReviewRows = (item: any, compact = false) => {
    const rows = getReviewRows(item);
    if (rows.length === 0) {
      return (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-700 dark:border-amber-900/40 dark:bg-amber-900/20 dark:text-amber-300">
          大模型未保留待提交物种；确认只更新 TaskItem 确认状态。
        </div>
      );
    }

    return (
      <div className={`space-y-2 ${compact ? 'text-xs' : 'text-sm'}`}>
        {rows.map((row: any, index: number) => (
          <div key={`${row.recordId ?? index}-${index}`} className="rounded-lg border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900/50 p-3">
            <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
              <span className="font-medium text-gray-900 dark:text-gray-100">结果 {index + 1}</span>
              <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${getDecisionClass(row)}`}>
                {getDecisionLabel(row)}
              </span>
            </div>
            <div className="grid grid-cols-[auto_minmax(0,1fr)_auto_minmax(0,1fr)_auto_minmax(4.5rem,5.5rem)_auto] items-center gap-2 min-w-0">
              <span className="whitespace-nowrap text-[11px] text-gray-500 dark:text-gray-400">原结果</span>
              <span className="min-w-0 truncate text-red-700 dark:text-red-300" title={row.originalName || '--'}>
                {row.originalName || '--'}
              </span>
              <label className="whitespace-nowrap text-[11px] text-gray-500 dark:text-gray-400">识别名称</label>
              <input
                type="text"
                value={getRowDraft(row).aiName}
                disabled={!isRowEditable(item)}
                onChange={(event) => setRowDraft(row, { aiName: event.target.value })}
                className="min-w-0 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-green-700 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-green-300 dark:disabled:bg-gray-900"
              />
              <label className="whitespace-nowrap text-[11px] text-gray-500 dark:text-gray-400">状态</label>
              <select
                value={getRowDraft(row).status}
                disabled={!isRowEditable(item)}
                onChange={(event) => setRowDraft(row, { status: event.target.value })}
                className="min-w-0 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-900 outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100 disabled:text-gray-500 dark:border-gray-600 dark:bg-gray-800 dark:text-gray-100 dark:disabled:bg-gray-900"
              >
                {reviewStatusOptions.map((status) => (
                  <option key={status} value={status}>{status}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => handleSaveRow(item, row)}
                disabled={!isRowEditable(item)}
                className="flex-none inline-flex items-center justify-center gap-1.5 rounded-md bg-blue-600 px-2.5 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:bg-gray-300 disabled:text-gray-500 dark:disabled:bg-gray-700 transition-colors"
                title="保存"
              >
                <Save className="w-3.5 h-3.5" />
                保存
              </button>
            </div>
            {row.errorMessage && (
              <div className="mt-2 text-[11px] text-gray-500 dark:text-gray-400">
                {row.errorMessage}
              </div>
            )}
          </div>
        ))}
      </div>
    );
  };

  const renderListView = () => (
    <div className="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm overflow-hidden transition-colors">
      <table className="w-full text-left border-collapse">
        <thead>
          <tr className="bg-gray-50 dark:bg-gray-900/50 border-b border-gray-200 dark:border-gray-700">
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">选择</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">缩略图</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">任务</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">原有系统</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">AI 多模态模型</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase">对比结果</th>
            <th className="px-4 py-3 text-xs font-semibold text-gray-500 dark:text-gray-400 uppercase text-right">操作</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
          {filteredItems.map(item => {
            const matched = isResultMatched(item);
            return (
            <tr key={item.id} className={`hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors ${matched ? 'border-l-4 border-l-green-500' : 'border-l-4 border-l-red-500'}`}>
              <td className="px-4 py-3 align-top">
                {renderSelectionCheckbox(item)}
              </td>
              <td className="px-4 py-3 whitespace-nowrap">
                <div className="w-16 rounded overflow-hidden bg-gray-100 dark:bg-gray-900 flex-shrink-0">
                  {item.mediaType === 'video' ? (
                    renderMedia(item, 'w-full h-full object-cover')
                  ) : (
                    <button
                      type="button"
                      onClick={() => openPreview(item)}
                      className="w-full cursor-zoom-in"
                      title="查看大图"
                    >
                      {renderImageWithBboxOverlay(item)}
                    </button>
                  )}
                </div>
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-sm font-medium text-gray-900 dark:text-gray-100">
                <div className="flex flex-col gap-2">
                  <div className="flex items-center gap-2">
                  <span>{item.taskName || '--'}</span>
                  {matched && (
                    <span className="inline-flex items-center rounded-md bg-green-600 px-2 py-0.5 text-xs font-bold text-white">
                      结果一致
                    </span>
                  )}
                  </div>
                  {renderSummaryBadges(item)}
                </div>
              </td>
              <td className="px-4 py-3 text-sm text-gray-500 dark:text-gray-400" colSpan={2}>
                {renderReviewRows(item, true)}
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-sm">
                <span className={`inline-flex items-center rounded-md px-2.5 py-1 font-medium ${matched ? 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
                  {matched ? '结果一致' : '结果不一致'}
                </span>
              </td>
              <td className="px-4 py-3 whitespace-nowrap text-right space-x-2">
                {renderItemActions(item)}
              </td>
            </tr>
          )})}
        </tbody>
      </table>
    </div>
  );

  const renderGridView = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
      {filteredItems.map((item) => {
        const matched = isResultMatched(item);
        return (
        <div key={item.id} className={`bg-white dark:bg-gray-800 rounded-xl border-2 shadow-sm overflow-hidden flex flex-col transition-colors ${matched ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400'}`}>
          <div className="w-full bg-gray-100 dark:bg-gray-900 relative">
            {item.mediaType === 'video' ? (
              renderMedia(item, 'w-full h-auto')
            ) : (
              <button
                type="button"
                onClick={() => openPreview(item)}
                className="w-full cursor-zoom-in text-left"
                title="查看大图"
              >
                {renderImageWithBboxOverlay(item)}
              </button>
            )}
            <div className="absolute top-2 left-2 bg-black/60 text-white text-xs px-2 py-1 rounded backdrop-blur-sm">
              {item.taskName || item.id}
            </div>
            {matched && (
              <div className="absolute top-2 right-2 bg-green-600 text-white text-xs font-bold px-2.5 py-1 rounded">
                结果一致
              </div>
            )}
            <div className="absolute bottom-2 left-2 rounded bg-white/90 px-2 py-1 dark:bg-gray-900/90">
              {renderSelectionCheckbox(item)}
            </div>
          </div>
          
          <div className="p-5 flex-1 flex flex-col justify-between">
            <div>
              <div className="mb-4">
                {renderSummaryBadges(item)}
              </div>
              {renderReviewRows(item, true)}
              {item.remoteError && (
                <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300">
                  {item.remoteError}
                </div>
              )}
            </div>

            <div className="mt-6">
              {renderItemActions(item)}
            </div>
          </div>
        </div>
      )})}
    </div>
  );

  const renderGalleryView = () => {
    const activeItem = filteredItems.find(i => String(i.id) === activeItemId) || filteredItems[0];
    if (!activeItem) return null;
    const activeIndex = filteredItems.findIndex(i => i.id === activeItem.id);
    const hasPrevious = activeIndex > 0;
    const hasNext = activeIndex < filteredItems.length - 1;
    const matched = isResultMatched(activeItem);

    return (
      <div className="flex flex-col lg:flex-row gap-4" style={{ height: 'calc(100vh - 220px)', minHeight: '480px' }}>
        {/* 左侧：图片 + 缩略图条 */}
        <div className={`flex-1 flex flex-col gap-3 bg-white dark:bg-gray-800 p-4 rounded-xl border-2 shadow-sm transition-colors min-w-0 ${matched ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400'}`}>
          <div className="flex-1 bg-gray-100 dark:bg-gray-900 rounded-lg overflow-hidden relative min-h-0">
            {activeItem.mediaType === 'video' ? (
              renderVideoWithBboxOverlay(activeItem, 'w-full h-full object-contain')
            ) : (
              <button
                type="button"
                onClick={() => openPreview(activeItem)}
                className="w-full h-full cursor-zoom-in"
                title="查看大图"
              >
                {renderImageWithBboxOverlay(activeItem, { contain: true })}
              </button>
            )}
            <div className="absolute top-3 left-3 bg-black/60 text-white text-xs px-2 py-1 rounded backdrop-blur-sm pointer-events-none">
              {activeItem.taskName || activeItem.id}
            </div>
            {matched && (
              <div className="absolute top-3 right-3 bg-green-600 text-white text-xs font-bold px-2 py-1 rounded pointer-events-none">
                结果一致
              </div>
            )}
            {filteredItems.length > 1 && (
              <>
                <button type="button" onClick={() => switchGalleryItem('prev')} disabled={!hasPrevious}
                  className="absolute left-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
                  title="上一个" aria-label="上一个">
                  <ChevronLeft className="w-5 h-5" />
                </button>
                <button type="button" onClick={() => switchGalleryItem('next')} disabled={!hasNext}
                  className="absolute right-3 top-1/2 -translate-y-1/2 h-9 w-9 rounded-full bg-black/60 text-white flex items-center justify-center hover:bg-black/80 disabled:opacity-35 disabled:cursor-not-allowed transition-colors"
                  title="下一个" aria-label="下一个">
                  <ChevronRight className="w-5 h-5" />
                </button>
              </>
            )}
            <div className="absolute bottom-3 left-3 rounded bg-white/90 px-2 py-1 dark:bg-gray-900/90">
              {renderSelectionCheckbox(activeItem)}
            </div>
          </div>
          {/* 缩略图条 */}
          <div className="flex gap-2 overflow-x-auto flex-shrink-0 pb-1">
            {filteredItems.map(item => (
              <button key={item.id} onClick={() => setActiveItemId(String(item.id))}
                className={`flex-shrink-0 w-20 h-14 rounded-md overflow-hidden border-2 transition-colors ${
                  activeItemId === String(item.id)
                    ? (isResultMatched(item) ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400')
                    : 'border-transparent opacity-60 hover:opacity-100'
                }`}>
                {item.mediaType === 'video' ? (
                  renderVideoWithBboxOverlay(item, 'w-full h-full object-cover')
                ) : (
                  <img src={item.imageUrl} className="w-full h-full object-cover" referrerPolicy="no-referrer" />
                )}
              </button>
            ))}
          </div>
        </div>

        {/* 右侧：识别详情（内部可滚动，整体不超出视口） */}
        <div className={`w-full lg:w-[30rem] flex flex-col bg-white dark:bg-gray-800 rounded-xl border-2 shadow-sm transition-colors overflow-hidden ${matched ? 'border-green-500 dark:border-green-400' : 'border-red-500 dark:border-red-400'}`}>
          <div className="p-4 border-b border-gray-200 dark:border-gray-700 flex-shrink-0">
            <h3 className="text-base font-semibold text-gray-900 dark:text-white">识别详情</h3>
            <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5 truncate">任务：{activeItem.taskName || '--'}</p>
            <div className="flex flex-wrap gap-2 mt-2">
              <span className={`inline-flex items-center rounded-md px-2.5 py-0.5 text-xs font-bold ${matched ? 'bg-green-600 text-white' : 'bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300'}`}>
                {matched ? '结果一致' : '结果不一致'}
              </span>
              {renderSummaryBadges(activeItem)}
            </div>
          </div>
          <div className="flex-1 overflow-y-auto p-4 space-y-3 min-h-0">
            {renderReviewRows(activeItem)}
            {activeItem.remoteError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-900/40 dark:bg-red-900/20 dark:text-red-300">
                {activeItem.remoteError}
              </div>
            )}
          </div>
          <div className="p-4 border-t border-gray-200 dark:border-gray-700 flex-shrink-0">
            {renderItemActions(activeItem, true)}
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="p-8">
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center mb-6 gap-4">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 dark:text-white">结果复核（TaskItem Actions）</h2>
          <p className="text-sm text-gray-500 dark:text-gray-400 mt-1">确认不提交远端；提交远端是独立操作。可编辑识别名称和状态，并对选中项批量处理。</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <select
            value={selectedTaskId}
            onChange={(e) => setSelectedTaskId(e.target.value)}
            className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg px-3 py-2 text-sm"
          >
            {taskOptions.map(task => (
              <option key={task.id} value={String(task.id)}>{task.name}</option>
            ))}
          </select>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setConsistencyFilter('all')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                consistencyFilter === 'all'
                  ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                  : 'bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300'
              }`}
            >
              全部 {totalCount}
            </button>
            <button
              type="button"
              onClick={() => setConsistencyFilter('matched')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                consistencyFilter === 'matched'
                  ? 'bg-green-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-green-300 dark:border-green-700 text-green-700 dark:text-green-300'
              }`}
            >
              一致 {matchedCount}
            </button>
            <button
              type="button"
              onClick={() => setConsistencyFilter('mismatched')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                consistencyFilter === 'mismatched'
                  ? 'bg-red-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-red-300 dark:border-red-700 text-red-700 dark:text-red-300'
              }`}
            >
              不一致 {mismatchedCount}
            </button>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setConfirmFilter('all')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                confirmFilter === 'all'
                  ? 'bg-gray-900 text-white dark:bg-white dark:text-gray-900'
                  : 'bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300'
              }`}
            >
              状态全部 {consistencyFilteredItems.length}
            </button>
            <button
              type="button"
              onClick={() => setConfirmFilter('pending')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                confirmFilter === 'pending'
                  ? 'bg-amber-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-amber-300 dark:border-amber-700 text-amber-700 dark:text-amber-300'
              }`}
            >
              待复核 {pendingConfirmCount}
            </button>
            <button
              type="button"
              onClick={() => setConfirmFilter('confirmed')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                confirmFilter === 'confirmed'
                  ? 'bg-blue-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-blue-300 dark:border-blue-700 text-blue-700 dark:text-blue-300'
              }`}
            >
              已确认 {confirmedCount}
            </button>
            <button
              type="button"
              onClick={() => setConfirmFilter('skipped')}
              className={`rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
                confirmFilter === 'skipped'
                  ? 'bg-gray-600 text-white'
                  : 'bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300'
              }`}
            >
              跳过 {skippedCount}
            </button>
          </div>

          <div className="flex bg-gray-100 dark:bg-gray-800 p-1 rounded-lg border border-gray-200 dark:border-gray-700">
            <button 
              onClick={() => setViewMode('list')}
              className={`p-1.5 rounded-md transition-colors ${viewMode === 'list' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}`}
              title="列表视图"
            >
              <List className="w-4 h-4" />
            </button>
            <button 
              onClick={() => setViewMode('grid')}
              className={`p-1.5 rounded-md transition-colors ${viewMode === 'grid' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}`}
              title="图标视图"
            >
              <LayoutGrid className="w-4 h-4" />
            </button>
            <button 
              onClick={() => setViewMode('gallery')}
              className={`p-1.5 rounded-md transition-colors ${viewMode === 'gallery' ? 'bg-white dark:bg-gray-700 text-gray-900 dark:text-white shadow-sm' : 'text-gray-500 dark:text-gray-400 hover:text-gray-900 dark:hover:text-gray-200'}`}
              title="画廊视图"
            >
              <ImageIcon className="w-4 h-4" />
            </button>
          </div>

          <div className="w-px h-6 bg-gray-300 dark:bg-gray-700 mx-1"></div>

          <span className="text-sm text-gray-500 dark:text-gray-400">
            已选 {selectedItemIds.length} 项
          </span>
          <button
            type="button"
            onClick={selectCurrentProcessableItems}
            className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 px-3 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
          >
            全选当前可处理项
          </button>
          <button
            type="button"
            onClick={clearSelection}
            disabled={selectedItemIds.length === 0}
            className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 px-3 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            清空选择
          </button>
          <button
            type="button"
            onClick={handleBatchConfirm}
            disabled={selectedConfirmableIds.length === 0}
            className="bg-blue-600 hover:bg-blue-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:bg-gray-300 disabled:text-gray-500"
          >
            批量确认
          </button>
          <button
            type="button"
            onClick={handleBatchSkip}
            disabled={selectedSkippableIds.length === 0}
            className="bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 text-gray-700 dark:text-gray-300 px-4 py-2 rounded-lg text-sm font-medium hover:bg-gray-50 dark:hover:bg-gray-700 disabled:opacity-50 transition-colors"
          >
            批量跳过
          </button>
          <button
            type="button"
            onClick={handleBatchSubmit}
            disabled={taskSubmittableIds.length === 0}
            className="bg-emerald-600 hover:bg-emerald-700 text-white px-4 py-2 rounded-lg text-sm font-medium transition-colors disabled:bg-gray-300 disabled:text-gray-500"
            title="提交当前任务下全部已确认且待提交或提交失败的复核项"
          >
            批量提交远端 {taskSubmittableIds.length}
          </button>
        </div>
      </div>

      {filteredItems.length === 0 ? (
        <div className="py-16 text-center text-gray-500 dark:text-gray-400 bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 border-dashed transition-colors">
          <CheckSquare className="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-3" />
          <p className="text-lg font-medium text-gray-900 dark:text-white">{items.length === 0 ? '全部处理完毕！' : '暂无匹配结果'}</p>
          <p>当前筛选下没有匹配的复核数据。</p>
        </div>
      ) : (
        <>
          {viewMode === 'list' && renderListView()}
          {viewMode === 'grid' && renderGridView()}
          {viewMode === 'gallery' && renderGalleryView()}
        </>
      )}

      {previewItem && (
        <div
          className="fixed inset-0 z-50 bg-black/85 flex items-center justify-center p-4"
          onClick={closePreview}
        >
          <div
            className="relative w-full max-w-6xl max-h-[92vh] rounded-xl bg-black border border-white/20 p-3"
            onClick={(e) => e.stopPropagation()}
          >
            <button
              type="button"
              onClick={closePreview}
              className="absolute right-3 top-3 z-10 h-8 w-8 rounded-full bg-black/60 text-white hover:bg-black/80 text-lg leading-none"
              aria-label="关闭预览"
            >
              ×
            </button>

            <div className="text-white text-sm mb-3 pr-10 truncate">
              {previewItem.taskName || previewItem.id}
            </div>

            <div className="w-full max-h-[78vh] flex items-center justify-center overflow-auto">
              {previewItem.mediaType === 'video' ? (
                renderVideoWithBboxOverlay(previewItem, 'max-h-[78vh] max-w-full rounded-md')
              ) : (
                <div className="w-full">
                  {renderImageWithBboxOverlay(previewItem)}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
