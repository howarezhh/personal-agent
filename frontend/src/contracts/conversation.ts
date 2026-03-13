import type { components } from './generated/openapi';

export type ConversationContract = components['schemas']['ConversationResponse'];
export type ConversationSummaryContract = components['schemas']['ConversationSummaryResponse'];
export type CreateConversationRequestContract = components['schemas']['CreateConversationRequest'];
export type UpdateConversationRequestContract = components['schemas']['UpdateConversationRequest'];

export type ConversationEnvelopeContract = components['schemas']['SuccessResponse_ConversationResponse_'];
export type PaginatedConversationSummaryResponseContract = components['schemas']['PaginatedResponse_ConversationSummaryResponse_'];
export type PaginatedConversationMessageResponseContract = components['schemas']['PaginatedResponse_ConversationMessageItem_'];
