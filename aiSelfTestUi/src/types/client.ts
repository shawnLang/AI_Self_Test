export type ClientStatus = '启用' | '停用';
export type ClientAuthStatus = '未认证' | '已认证' | '即将过期';

export interface ClientItem {
  id: number;
  name: string;
  apiUrl: string;
  account: string;
  status: ClientStatus;
  authStatus: ClientAuthStatus;
  password: string;
  accessToken: string;
  refreshToken: string;
  expiresIn: number | null;
}

export interface ClientListData {
  items: ClientItem[];
}

export interface ClientFormData {
  name: string;
  apiUrl: string;
  account: string;
  password: string;
  status: ClientStatus;
}

export interface ClientAuthenticateData {
  client: ClientItem;
  usedStrategy: 'reuse' | 'refresh' | 'login';
}
