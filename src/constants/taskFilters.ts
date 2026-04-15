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

export const intervalOptions = [
  '每 15 分钟',
  '每 30 分钟',
  '每小时',
  '每 6 小时',
  '每天 00:00'
];
