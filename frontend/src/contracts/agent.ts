import type { components } from './generated/openapi';

export type WorkflowContextContract = components['schemas']['WorkflowContextSchema'];

export type AgentInputContract = components['schemas']['AgentInputSchema'];
export type RouterAgentInputContract = components['schemas']['RouterAgentInputSchema'];
export type RetrievalAgentInputContract = components['schemas']['RetrievalAgentInputSchema'];
export type GenerationAgentInputContract = components['schemas']['GenerationAgentInputSchema'];
export type ToolAgentInputContract = components['schemas']['ToolAgentInputSchema'];
export type FileProcessorAgentInputContract = components['schemas']['FileProcessorAgentInputSchema'];

export type AgentOutputContract = components['schemas']['AgentOutputSchema'];
export type RouterAgentOutputContract = components['schemas']['RouterAgentOutputSchema'];
export type RetrievalAgentOutputContract = components['schemas']['RetrievalAgentOutputSchema'];
export type GenerationAgentOutputContract = components['schemas']['GenerationAgentOutputSchema'];
export type ToolAgentOutputContract = components['schemas']['ToolAgentOutputSchema'];
export type FileProcessorAgentOutputContract = components['schemas']['FileProcessorAgentOutputSchema'];
