import type { AuthTokenEnvelopeContract, UserProfileEnvelopeContract } from '@/contracts/auth';
import {
  adaptTokenResponse,
  adaptUserProfile,
  toLoginRequestContract,
  toRegisterRequestContract,
} from '@/adapters/authAdapter';
import type { LoginRequest, RegisterRequest, TokenResponse, User } from '@/types';
import { API_PATHS } from '@/constants/api';
import api from './api';

export const authService = {
  async register(data: RegisterRequest): Promise<TokenResponse> {
    const response = await api.post<AuthTokenEnvelopeContract>(
      API_PATHS.auth.register,
      toRegisterRequestContract(data)
    );
    return adaptTokenResponse(response.data.data!);
  },

  async login(data: LoginRequest): Promise<TokenResponse> {
    const response = await api.post<AuthTokenEnvelopeContract>(
      API_PATHS.auth.login,
      toLoginRequestContract(data)
    );
    return adaptTokenResponse(response.data.data!);
  },

  async logout(): Promise<void> {
    await api.post(API_PATHS.auth.logout);
  },

  async getProfile(): Promise<User> {
    const response = await api.get<UserProfileEnvelopeContract>(API_PATHS.auth.profile);
    return adaptUserProfile(response.data.data!);
  },

  async refreshToken(refreshToken: string): Promise<TokenResponse> {
    const response = await api.post<AuthTokenEnvelopeContract>(API_PATHS.auth.refresh, {
      refresh_token: refreshToken,
    });
    return adaptTokenResponse(response.data.data!);
  },
};
