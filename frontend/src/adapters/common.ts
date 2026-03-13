import type { ErrorResponseContract, PaginationMetaContract } from '@/contracts/common';

export interface ErrorDetail {
  field?: string;
  message: string;
  type?: string;
}

export interface AppError {
  code: number;
  message: string;
  error: string;
  errorCode: string;
  details?: ErrorDetail[];
  timestamp: string;
}

export interface PaginationMeta {
  total: number;
  page: number;
  pageSize: number;
  totalPages: number;
  hasNext: boolean;
  hasPrev: boolean;
}

export const adaptError = (error: ErrorResponseContract): AppError => ({
  code: error.code,
  message: error.message,
  error: error.error,
  errorCode: error.error_code ?? 'SYSTEM_HTTP_ERROR',
  details: error.details?.map((detail) => ({
    field: detail.field ?? undefined,
    message: detail.message,
    type: detail.type ?? undefined,
  })),
  timestamp: error.timestamp ?? new Date().toISOString(),
});

export const adaptPagination = (pagination: PaginationMetaContract): PaginationMeta => ({
  total: pagination.total,
  page: pagination.page,
  pageSize: pagination.page_size,
  totalPages: pagination.total_pages,
  hasNext: pagination.has_next,
  hasPrev: pagination.has_prev,
});
