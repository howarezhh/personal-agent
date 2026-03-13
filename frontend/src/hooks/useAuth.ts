import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

import { authService } from '@/services/authService';
import { authSession } from '@/services/authSession';
import { useAuthStore } from '@/stores/authStore';
import type { LoginRequest, RegisterRequest } from '@/types';

export const useAuth = () => {
  const navigate = useNavigate();
  const { user, isAuthenticated, isLoading, setUser, setAuthenticated, setLoading, logout: storeLogout } =
    useAuthStore();

  useEffect(() => {
    const checkAuth = async () => {
      const token = authSession.getAccessToken();
      if (!token) {
        setLoading(false);
        setAuthenticated(false);
        return;
      }

      try {
        const profile = await authService.getProfile();
        setUser(profile);
        setAuthenticated(true);
      } catch {
        authSession.clear();
        setAuthenticated(false);
      } finally {
        setLoading(false);
      }
    };

    void checkAuth();
  }, [setAuthenticated, setLoading, setUser]);

  const login = async (data: LoginRequest) => {
    try {
      const response = await authService.login(data);
      authSession.setTokens(response.accessToken, response.refreshToken);
      const profile = await authService.getProfile();
      setUser(profile);
      setAuthenticated(true);
      navigate('/');
    } catch (error: any) {
      throw new Error(error.response?.data?.message || error.message || '登录失败');
    }
  };

  const register = async (data: RegisterRequest) => {
    try {
      const response = await authService.register(data);
      authSession.setTokens(response.accessToken, response.refreshToken);
      const profile = await authService.getProfile();
      setUser(profile);
      setAuthenticated(true);
      navigate('/');
    } catch (error: any) {
      throw new Error(error.response?.data?.message || error.message || '注册失败');
    }
  };

  const logout = async () => {
    try {
      await authService.logout();
    } finally {
      storeLogout();
      navigate('/login');
    }
  };

  return { user, isAuthenticated, isLoading, login, register, logout };
};

