import axios from 'axios';

import type { AuthTokenEnvelopeContract } from '@/contracts/auth';
import type { ErrorResponseContract } from '@/contracts/common';
import { API_BASE_URL, API_PATHS } from '@/constants/api';

import { authSession } from './authSession';

let refreshRequest: Promise<string> | null = null;

const redirectToLogin = () => {
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
};

export const clearAuthAndRedirect = () => {
  authSession.clear();
  redirectToLogin();
};

export const refreshAccessToken = async (): Promise<string> => {
  if (refreshRequest) {
    return refreshRequest;
  }

  const refreshToken = authSession.getRefreshToken();
  if (!refreshToken) {
    clearAuthAndRedirect();
    throw new Error('登录已过期，请重新登录');
  }

  refreshRequest = axios
    .post<AuthTokenEnvelopeContract>(`${API_BASE_URL}${API_PATHS.auth.refresh}`, {
      refresh_token: refreshToken,
    })
    .then((response) => {
      const { access_token, refresh_token } = response.data.data!;
      authSession.setTokens(access_token, refresh_token);
      return access_token;
    })
    .catch((error: { response?: { data?: ErrorResponseContract } }) => {
      clearAuthAndRedirect();
      const message = error.response?.data?.message || '登录已过期，请重新登录';
      throw new Error(message);
    })
    .finally(() => {
      refreshRequest = null;
    });

  return refreshRequest;
};

export const shouldAttemptTokenRefresh = (requestUrl?: string) => {
  if (!requestUrl) {
    return true;
  }

  return ![
    API_PATHS.auth.login,
    API_PATHS.auth.register,
    API_PATHS.auth.refresh,
  ].some((path) => requestUrl.includes(path));
};
