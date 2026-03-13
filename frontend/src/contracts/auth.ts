import type { components } from './generated/openapi';

export type LoginRequestContract = components['schemas']['LoginRequest'];
export type RegisterRequestContract = components['schemas']['RegisterRequest'];
export type RefreshTokenRequestContract = components['schemas']['RefreshTokenRequest'];
export type TokenResponseContract = components['schemas']['TokenResponse'];
export type UserProfileResponseContract = components['schemas']['UserProfileResponse'];
export type LogoutResponseContract = components['schemas']['LogoutResponse'];

export type AuthTokenEnvelopeContract = components['schemas']['SuccessResponse_TokenResponse_'];
export type UserProfileEnvelopeContract = components['schemas']['SuccessResponse_UserProfileResponse_'];
export type LogoutEnvelopeContract = components['schemas']['SuccessResponse_LogoutResponse_'];
