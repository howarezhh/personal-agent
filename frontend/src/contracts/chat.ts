import type { components } from './generated/openapi';

export type MessageContract = components['schemas']['ConversationMessageItem'];
export type AskRequestContract = components['schemas']['AskRequest'];
export type AskResponseContract = components['schemas']['AskResponse'];
export type SSEEventContract = components['schemas']['SSEEvent'];
export type ChatResultPayloadContract = components['schemas']['ChatResultPayload'];
export type ChatDonePayloadContract = components['schemas']['ChatDonePayload'];
export type PauseRequestContract = components['schemas']['PauseRequest'];
export type PauseStreamResponseContract = components['schemas']['PauseStreamResponse'];

export type AskEnvelopeContract = components['schemas']['SuccessResponse_AskResponse_'];
export type PauseEnvelopeContract = components['schemas']['SuccessResponse_PauseStreamResponse_'];
