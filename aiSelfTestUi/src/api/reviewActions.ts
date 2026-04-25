import { deleteReviewItems } from './taskItems';

export async function deleteReviewItem(id: string): Promise<void> {
  const result = await deleteReviewItems([id]);
  if (result.failureCount > 0) {
    const failure = result.results.find((item) => item.status === 'failed');
    throw new Error(failure?.message || '删除复核差异失败');
  }
}
