import { useMemo } from 'react';
import type { ReviewItem } from '../api/review';

export type ConsistencyFilter = 'all' | 'matched' | 'mismatched';

export function normalizeCompareValue(value: string) {
  return String(value || '').trim().toLowerCase().replace(/\s+/g, '');
}

export function getCompareTokens(value: string) {
  const trimmed = String(value || '').trim();
  if (!trimmed) return [];

  const parts = trimmed
    .split(/[、,，;；|/]+/)
    .map(normalizeCompareValue)
    .filter(Boolean);

  return parts.length > 0 ? parts : [normalizeCompareValue(trimmed)];
}

export function getReviewRows(item: ReviewItem) {
  if (Array.isArray(item.reviewRows)) return item.reviewRows;
  const aiValue = normalizeCompareValue(item.aiResult || '');
  const originalTokens = getCompareTokens(item.originalResult || '');
  const matched = Boolean(aiValue)
    && !aiValue.startsWith('识别失败:')
    && originalTokens.some((token) => token === aiValue || token.includes(aiValue) || aiValue.includes(token));

  return [{
    originalName: item.originalResult,
    aiName: item.aiResult,
    decision: matched ? 'keep' : 'rename',
    willSubmit: Boolean(item.aiResult),
    groundingStatus: 'legacy',
    legacy: true,
  }];
}

export function isResultMatched(item: ReviewItem) {
  const rows = getReviewRows(item);
  if (Array.isArray(item.reviewRows)) {
    return rows.length > 0 && rows.every((row: any) => row.decision === 'keep' && row.willSubmit);
  }

  const aiValue = normalizeCompareValue(item.aiResult || '');
  if (!aiValue || aiValue.startsWith('识别失败:')) return false;

  const originalTokens = getCompareTokens(item.originalResult || '');
  if (originalTokens.length === 0) return false;

  return originalTokens.some((token) => token === aiValue || token.includes(aiValue) || aiValue.includes(token));
}

export function useReviewItem(items: ReviewItem[], consistencyFilter: ConsistencyFilter) {
  return useMemo(() => {
    const filteredItems = items.filter((item) => {
      const matched = isResultMatched(item);
      if (consistencyFilter === 'matched') return matched;
      if (consistencyFilter === 'mismatched') return !matched;
      return true;
    });
    const matchedCount = items.filter((item) => isResultMatched(item)).length;

    return {
      filteredItems,
      matchedCount,
      mismatchedCount: items.length - matchedCount,
      totalCount: items.length,
    };
  }, [items, consistencyFilter]);
}
