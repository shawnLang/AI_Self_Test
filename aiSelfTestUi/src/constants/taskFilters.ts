export type TaskFilterFormData = {
  classifyList: number[];
  keyword: string;
  spName: string;
  startTime: string;
  endTime: string;
  fileBmp: string;
  uploadType: string;
  idType: string;
  size: number;
  current: number;
};

export const fileBmpOptions = [
  { value: 'image', label: '图片', apiValue: 1 },
  { value: 'video', label: '视频', apiValue: 2 },
  { value: 'audio', label: '音频', apiValue: 3 }
] as const;

export const classifyOptions = [
  { value: 1, label: '确种' },
  { value: 2, label: '有效' },
  { value: 3, label: '空拍' },
  { value: 4, label: '处理中' }
];

export const defaultTaskFilters: TaskFilterFormData = {
  classifyList: [1, 2],
  keyword: '',
  spName: '',
  startTime: '',
  endTime: '',
  fileBmp: 'all',
  uploadType: 'all',
  idType: 'all',
  size: 50,
  current: 1
};

const fileBmpValueMap: Record<string, TaskFilterFormData['fileBmp']> = {
  all: 'all',
  image: 'image',
  video: 'video',
  audio: 'audio',
  '0': 'image',
  '1': 'image',
  '2': 'video',
  '3': 'audio'
};

const normalizeDateInputValue = (value: unknown) => {
  const trimmed = String(value || '').trim();
  if (!trimmed) return '';

  const match = trimmed.match(/^(\d{4}-\d{2}-\d{2})/);
  return match ? match[1] : trimmed;
};

export const normalizeTaskFiltersForForm = (filters: Record<string, unknown> | Partial<TaskFilterFormData> | null | undefined): TaskFilterFormData => {
  const source = filters && typeof filters === 'object' ? filters as Record<string, unknown> : {};
  const classifyList = source.classifyList ?? source.classify_list;
  const mediaTypes = Array.isArray(source.media_types) ? source.media_types : [];
  const uploadTypes = source.uploadType ?? source.upload_types;
  const identifySource = source.idType ?? source.identify_source;
  const canonicalFileBmp = mediaTypes.length === 1 ? mediaTypes[0] : undefined;
  const canonicalUploadType = Array.isArray(uploadTypes) ? uploadTypes[0] : uploadTypes;
  const canonicalIdType = Array.isArray(identifySource) ? identifySource[0] : identifySource;

  return {
    classifyList: Array.isArray(classifyList)
      ? classifyList.map(Number).filter((value) => Number.isFinite(value))
      : [...defaultTaskFilters.classifyList],
    keyword: String(source.keyword || '').trim(),
    spName: String(source.spName ?? source.sp_name ?? '').trim(),
    startTime: normalizeDateInputValue(source.startTime ?? source.start_at),
    endTime: normalizeDateInputValue(source.endTime ?? source.end_at),
    fileBmp: fileBmpValueMap[String(source.fileBmp ?? canonicalFileBmp ?? 'all').trim()] || 'all',
    uploadType: canonicalUploadType === undefined || canonicalUploadType === null || canonicalUploadType === '' ? 'all' : String(canonicalUploadType),
    idType: canonicalIdType === undefined || canonicalIdType === null || canonicalIdType === '' ? 'all' : String(canonicalIdType),
    size: Number(source.size) > 0 ? Number(source.size) : defaultTaskFilters.size,
    current: Number(source.current) > 0 ? Number(source.current) : defaultTaskFilters.current
  };
};

export const resolveApiFileBmpValue = (fileBmp: string) => {
  const option = fileBmpOptions.find((item) => item.value === fileBmp);
  return option ? option.apiValue : null;
};

export const intervalOptions = [
  '每 15 分钟',
  '每 30 分钟',
  '每小时',
  '每 6 小时',
  '每天 00:00'
];
