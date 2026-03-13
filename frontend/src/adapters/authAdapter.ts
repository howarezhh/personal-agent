import type { TokenResponseContract, UserProfileResponseContract } from '@/contracts/auth';

export interface User {
  userId: string;
  username: string;
  email: string;
  fullName?: string;
  avatarUrl?: string;
  isActive: boolean;
  createdAt: string;
}

export interface LoginRequest {
  usernameOrEmail: string;
  password: string;
}

export interface RegisterRequest {
  username: string;
  email: string;
  password: string;
  fullName?: string;
}

export interface TokenResponse {
  accessToken: string;
  refreshToken: string;
  tokenType: string;
  userId: string;
  username: string;
}

export const adaptTokenResponse = (token: TokenResponseContract): TokenResponse => ({
  accessToken: token.access_token,
  refreshToken: token.refresh_token,
  tokenType: token.token_type,
  userId: token.user_id,
  username: token.username,
});

export const adaptUserProfile = (user: UserProfileResponseContract): User => ({
  userId: user.user_id,
  username: user.username,
  email: user.email,
  fullName: user.full_name ?? undefined,
  avatarUrl: user.avatar_url ?? undefined,
  isActive: user.is_active,
  createdAt: user.created_at,
});

export const toLoginRequestContract = (data: LoginRequest) => ({
  username_or_email: data.usernameOrEmail,
  password: data.password,
});

export const toRegisterRequestContract = (data: RegisterRequest) => ({
  username: data.username,
  email: data.email,
  password: data.password,
  full_name: data.fullName,
});
