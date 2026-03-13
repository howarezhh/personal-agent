import axios from 'axios';
import type { ErrorResponseContract } from '@/contracts/common';
import { API_BASE_URL } from '@/constants/api';
import { authSession } from './authSession';
import { clearAuthAndRedirect, refreshAccessToken, shouldAttemptTokenRefresh } from './tokenRefresh';

const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = authSession.getAccessToken();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (
      error.response?.status === 401 &&
      !originalRequest?._retry &&
      shouldAttemptTokenRefresh(originalRequest?.url)
    ) {
      originalRequest._retry = true;

      try {
        const accessToken = await refreshAccessToken();

        originalRequest.headers = originalRequest.headers ?? {};
        originalRequest.headers.Authorization = `Bearer ${accessToken}`;
        return api(originalRequest);
      } catch (refreshError) {
        clearAuthAndRedirect();
        return Promise.reject(refreshError);
      }
    }

    const responseData = error.response?.data as ErrorResponseContract | undefined;
    if (responseData?.message) {
      error.message = responseData.message;
    }
    if (responseData?.error_code) {
      error.errorCode = responseData.error_code;
    }

    return Promise.reject(error);
  }
);

export default api;
