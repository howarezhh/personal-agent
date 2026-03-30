import { expect, type Page, test } from '@playwright/test';

const NOW = '2026-03-24T00:00:00.000Z';
const CONVERSATION_ID = 'conv_e2e_task_runtime_1';
const GOAL_ID = 'goal_e2e_task_runtime_1';
const PLAN_ID = 'plan_e2e_task_runtime_1';
const EXECUTION_ID = 'exec_e2e_task_runtime_1';
const TASK_ID = 'task_e2e_task_runtime_1';
const CHECKPOINT_ID = 'ckpt_e2e_task_runtime_1';

type JsonValue = string | number | boolean | null | JsonObject | JsonValue[];
type JsonObject = { [key: string]: JsonValue };

interface TaskRuntimeMockOptions {
  prepareFails?: boolean;
  streamScenario?: 'success' | 'pause_resume' | 'failure';
}

const buildSuccessEnvelope = (data: JsonValue): JsonObject => ({
  code: 200,
  message: 'success',
  data,
  timestamp: NOW,
});

const buildPagination = (total: number): JsonObject => ({
  total,
  page: 1,
  page_size: 100,
  total_pages: 1,
  has_next: false,
  has_prev: false,
});

const buildPaginatedEnvelope = (data: JsonValue[]): JsonObject => ({
  code: 200,
  message: 'success',
  data,
  pagination: buildPagination(data.length),
  timestamp: NOW,
});

const buildSseChunk = (event: JsonObject): string => `data: ${JSON.stringify(event)}

`;

const delay = async (milliseconds: number): Promise<void> => {
  await new Promise((resolve) => setTimeout(resolve, milliseconds));
};

const buildGoal = (userInput: string): JsonObject => ({
  goal_id: GOAL_ID,
  conversation_id: CONVERSATION_ID,
  source_message_id: 'msg_prepare',
  original_user_input: userInput,
  normalized_goal: '整理需求并输出计划',
  success_criteria: ['输出执行计划', '生成最终答案'],
  constraints: {},
  metadata: {},
});

const buildPlan = (): JsonObject => ({
  plan_id: PLAN_ID,
  goal_id: GOAL_ID,
  version: 1,
  reasoning: '先检索，再整合结果。',
  steps: [
    {
      step_id: 'step_retrieve_1',
      step_type: 'retrieve',
      title: '检索背景信息',
      description: '查询相关资料并整理要点。',
      depends_on: [],
      metadata: {},
    },
    {
      step_id: 'step_answer_1',
      step_type: 'synthesize_answer',
      title: '输出最终答复',
      description: '整理并输出最终结论。',
      depends_on: ['step_retrieve_1'],
      metadata: {},
    },
  ],
  metadata: {},
});

/**
 * 统一构造任务状态快照，模拟窗口 4 依赖的 status / checkpoint / artifact / final_report 结构。
 */
const buildTaskStatusSnapshot = (userInput: string, overrides: JsonObject = {}): JsonObject => ({
  task_id: TASK_ID,
  request_id: 'req_e2e_task_runtime_1',
  execution_id: EXECUTION_ID,
  status: 'pending',
  checkpoint_id: null,
  current_plan_id: PLAN_ID,
  current_step_id: null,
  created_at: NOW,
  updated_at: NOW,
  metadata: {},
  goal: buildGoal(userInput),
  current_plan: buildPlan(),
  termination: null,
  latest_checkpoint: null,
  artifacts: [],
  evaluation_report: null,
  ...overrides,
});

const buildActionResponse = (
  action: 'pause' | 'resume' | 'cancel' | 'retry',
  status: string,
  detailMessage: string,
): JsonObject => ({
  task_id: TASK_ID,
  request_id: 'req_e2e_task_runtime_1',
  execution_id: EXECUTION_ID,
  status,
  checkpoint_id: action === 'pause' ? CHECKPOINT_ID : null,
  current_plan_id: PLAN_ID,
  current_step_id: action === 'pause' ? 'step_retrieve_1' : null,
  created_at: NOW,
  updated_at: NOW,
  metadata: {},
  action,
  accepted: true,
  detail_message: detailMessage,
});

const buildConversationMessage = (
  sequenceNumber: number,
  messageType: 'user' | 'assistant',
  content: string,
  messageId: string,
): JsonObject => ({
  message_id: messageId,
  conversation_id: CONVERSATION_ID,
  message_type: messageType,
  content,
  sequence_number: sequenceNumber,
  parent_message_id: messageType === 'assistant' ? 'msg_prepare' : null,
  created_at: NOW,
  metadata: {},
});

async function registerTaskRuntimeMockRoutes(page: Page, options: TaskRuntimeMockOptions = {}): Promise<void> {
  let requestId = 'req_e2e_task_runtime_1';
  let messageId = 'msg_prepare';
  let latestUserInput = '请帮我整理需求并给出执行计划';
  let conversationCreated = false;
  let conversationMessages: JsonObject[] = [];
  let taskStatusSnapshot = buildTaskStatusSnapshot(latestUserInput);

  const setSucceededSnapshot = (finalOutput: string, summary: string, artifactTitle: string) => {
    taskStatusSnapshot = buildTaskStatusSnapshot(latestUserInput, {
      status: 'succeeded',
      current_step_id: 'step_answer_1',
      checkpoint_id: CHECKPOINT_ID,
      termination: {
        status: 'succeeded',
        reason: '任务执行完成。',
        final_output: finalOutput,
        metadata: {},
      },
      latest_checkpoint: {
        checkpoint_id: CHECKPOINT_ID,
        task_id: TASK_ID,
        execution_id: EXECUTION_ID,
        status: 'succeeded',
        iteration_count: 1,
        completed_step_ids: ['step_retrieve_1', 'step_answer_1'],
        latest_plan_id: PLAN_ID,
        latest_step_id: 'step_answer_1',
        checkpoint_reason: '步骤完成后自动归档',
        created_at: NOW,
        metadata: {},
      },
      artifacts: [
        {
          artifact_id: 'artifact_e2e_1',
          artifact_type: 'report',
          title: artifactTitle,
          content: finalOutput,
          source_plan_id: PLAN_ID,
          source_step_id: 'step_answer_1',
          created_at: NOW,
          metadata: {},
        },
      ],
      evaluation_report: {
        report_id: 'report_e2e_1',
        task_id: TASK_ID,
        success: true,
        overall_score: 96,
        summary,
        satisfied_criteria: ['输出执行计划', '生成最终答案'],
        missing_criteria: [],
        risks: [],
        recommendations: ['可以继续补充更多证据来源'],
        created_at: NOW,
        metadata: {},
      },
    });
  };

  await page.route('**/api/**', async (route) => {
    const request = route.request();
    const requestUrl = new URL(request.url());
    const pathname = requestUrl.pathname;
    const method = request.method();

    if (pathname === '/api/v1/auth/profile' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(
          buildSuccessEnvelope({
            user_id: 'user_e2e_1',
            username: 'playwright-user',
            email: 'playwright@example.com',
            full_name: 'Playwright User',
            avatar_url: null,
            is_active: true,
            created_at: NOW,
          }),
        ),
      });
      return;
    }

    if (pathname === '/api/v1/knowledge/bases' && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildSuccessEnvelope({ knowledge_bases: [], total: 0 })),
      });
      return;
    }

    if (pathname === '/api/v1/conversations' && method === 'GET') {
      const data = conversationCreated
        ? [{
          conversation_id: CONVERSATION_ID,
          title: latestUserInput,
          message_count: conversationMessages.length,
          last_message_preview: conversationMessages.length > 0
            ? String(conversationMessages[conversationMessages.length - 1]?.content ?? '')
            : '',
          updated_at: NOW,
        }]
        : [];

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildPaginatedEnvelope(data)),
      });
      return;
    }

    if (pathname === '/api/v1/conversations' && method === 'POST') {
      conversationCreated = true;
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(
          buildSuccessEnvelope({
            conversation_id: CONVERSATION_ID,
            user_id: 'user_e2e_1',
            title: latestUserInput,
            description: null,
            message_count: conversationMessages.length,
            is_active: true,
            created_at: NOW,
            updated_at: NOW,
          }),
        ),
      });
      return;
    }

    if (pathname === `/api/v1/conversations/${CONVERSATION_ID}` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(
          buildSuccessEnvelope({
            conversation_id: CONVERSATION_ID,
            user_id: 'user_e2e_1',
            title: latestUserInput,
            description: null,
            message_count: conversationMessages.length,
            is_active: true,
            created_at: NOW,
            updated_at: NOW,
          }),
        ),
      });
      return;
    }

    if (pathname === `/api/v1/conversations/${CONVERSATION_ID}/messages` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildPaginatedEnvelope(conversationMessages)),
      });
      return;
    }

    if (pathname === '/api/v1/task-runtime/tasks' && method === 'POST') {
      if (options.prepareFails) {
        await route.fulfill({
          status: 404,
          contentType: 'application/json; charset=utf-8',
          body: JSON.stringify({
            code: 404,
            message: '知识库不存在或无权访问',
            error: 'KnowledgeBaseNotFound',
            error_code: 'KNOWLEDGE_BASE_NOT_FOUND',
            timestamp: NOW,
          }),
        });
        return;
      }

      const payload = request.postDataJSON() as Record<string, string | undefined>;
      requestId = payload.request_id || requestId;
      messageId = payload.message_id || messageId;
      latestUserInput = payload.user_input || latestUserInput;
      taskStatusSnapshot = buildTaskStatusSnapshot(latestUserInput, {
        request_id: requestId,
        status: options.streamScenario === 'pause_resume' ? 'running' : 'pending',
      });

      conversationMessages = [
        buildConversationMessage(1, 'user', latestUserInput, messageId),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(
          buildSuccessEnvelope({
            task_id: TASK_ID,
            request_id: requestId,
            execution_id: EXECUTION_ID,
            status: options.streamScenario === 'pause_resume' ? 'running' : 'pending',
            checkpoint_id: null,
            current_plan_id: PLAN_ID,
            current_step_id: null,
            created_at: NOW,
            updated_at: NOW,
            metadata: {},
            goal: buildGoal(latestUserInput),
            plan: buildPlan(),
            evaluation_report: null,
          }),
        ),
      });
      return;
    }

    if (pathname === '/api/v1/task-runtime/tasks/stream' && method === 'POST') {
      if (options.streamScenario === 'pause_resume') {
        await delay(2500);
        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream; charset=utf-8',
          headers: {
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          },
          body: buildSseChunk({
            type: 'thinking',
            message: '流式执行已启动。',
            content: {
              step: {
                step_id: 'step_retrieve_1',
                step_type: 'retrieve',
                title: '检索背景信息',
                description: '查询相关资料并整理要点。',
              },
            },
            metadata: {
              stage: 'step_started',
              plan_id: PLAN_ID,
              step_id: 'step_retrieve_1',
              request_id: requestId,
              execution_id: EXECUTION_ID,
            },
            timestamp: NOW,
            request_id: requestId,
            conversation_id: CONVERSATION_ID,
            message_id: messageId,
            execution_id: EXECUTION_ID,
          }),
        });
        return;
      }

      if (options.streamScenario === 'failure') {
        taskStatusSnapshot = buildTaskStatusSnapshot(latestUserInput, {
          request_id: requestId,
          status: 'failed',
          current_step_id: 'step_answer_1',
          termination: {
            status: 'failed',
            reason: '任务执行失败：缺少关键输入。',
            final_output: null,
            metadata: {},
          },
          latest_checkpoint: {
            checkpoint_id: CHECKPOINT_ID,
            task_id: TASK_ID,
            execution_id: EXECUTION_ID,
            status: 'failed',
            iteration_count: 1,
            completed_step_ids: ['step_retrieve_1'],
            latest_plan_id: PLAN_ID,
            latest_step_id: 'step_answer_1',
            checkpoint_reason: '执行失败后保留现场',
            created_at: NOW,
            metadata: {},
          },
        });

        await route.fulfill({
          status: 200,
          contentType: 'text/event-stream; charset=utf-8',
          headers: {
            'Cache-Control': 'no-cache',
            Connection: 'keep-alive',
          },
          body: [
            buildSseChunk({
              type: 'thinking',
              message: '开始执行计划步骤。',
              content: {
                step: {
                  step_id: 'step_answer_1',
                  step_type: 'synthesize_answer',
                  title: '输出最终答复',
                  description: '整理并输出最终结论。',
                },
              },
              metadata: {
                stage: 'step_started',
                plan_id: PLAN_ID,
                step_id: 'step_answer_1',
                request_id: requestId,
                execution_id: EXECUTION_ID,
              },
              timestamp: NOW,
              request_id: requestId,
              conversation_id: CONVERSATION_ID,
              message_id: messageId,
              execution_id: EXECUTION_ID,
            }),
            buildSseChunk({
              type: 'error',
              message: '任务执行失败：缺少关键输入。',
              content: {
                status: 'failed',
                reason: '任务执行失败：缺少关键输入。',
              },
              metadata: {
                stage: 'termination',
                plan_id: PLAN_ID,
                request_id: requestId,
                execution_id: EXECUTION_ID,
              },
              timestamp: NOW,
              request_id: requestId,
              conversation_id: CONVERSATION_ID,
              message_id: messageId,
              execution_id: EXECUTION_ID,
            }),
          ].join(''),
        });
        return;
      }

      setSucceededSnapshot('最终执行结果：已整理完成。', '复杂任务已达成目标，验收通过。', '最终执行报告');
      conversationMessages = [
        buildConversationMessage(1, 'user', latestUserInput, messageId),
        buildConversationMessage(2, 'assistant', '最终执行结果：已整理完成。', 'msg_assistant_1'),
      ];

      await route.fulfill({
        status: 200,
        contentType: 'text/event-stream; charset=utf-8',
        headers: {
          'Cache-Control': 'no-cache',
          Connection: 'keep-alive',
        },
        body: [
          buildSseChunk({
            type: 'thinking',
            message: '开始执行计划步骤。',
            content: {
              step: {
                step_id: 'step_answer_1',
                step_type: 'synthesize_answer',
                title: '输出最终答复',
                description: '整理并输出最终结论。',
              },
            },
            metadata: {
              stage: 'step_started',
              plan_id: PLAN_ID,
              step_id: 'step_answer_1',
              request_id: requestId,
              execution_id: EXECUTION_ID,
            },
            timestamp: NOW,
            request_id: requestId,
            conversation_id: CONVERSATION_ID,
            message_id: messageId,
            execution_id: EXECUTION_ID,
          }),
          buildSseChunk({
            type: 'content',
            message: '正在输出最终结论。',
            content: '正在生成最终执行结果...',
            metadata: {
              stage: 'step_observation',
              plan_id: PLAN_ID,
              step_id: 'step_answer_1',
              request_id: requestId,
              execution_id: EXECUTION_ID,
            },
            timestamp: NOW,
            request_id: requestId,
            conversation_id: CONVERSATION_ID,
            message_id: messageId,
            execution_id: EXECUTION_ID,
          }),
          buildSseChunk({
            type: 'done',
            message: '任务执行完成。',
            content: {
              final_output: '最终执行结果：已整理完成。',
            },
            citations: [
              { source: 'kb-1', content: '引用片段' },
            ],
            metadata: {
              stage: 'termination',
              plan_id: PLAN_ID,
              request_id: requestId,
              execution_id: EXECUTION_ID,
            },
            timestamp: NOW,
            request_id: requestId,
            conversation_id: CONVERSATION_ID,
            message_id: messageId,
            execution_id: EXECUTION_ID,
          }),
        ].join(''),
      });
      return;
    }

    if (pathname === `/api/v1/task-runtime/tasks/${TASK_ID}` && method === 'GET') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildSuccessEnvelope(taskStatusSnapshot)),
      });
      return;
    }

    if (pathname === `/api/v1/task-runtime/tasks/${TASK_ID}/pause` && method === 'POST') {
      taskStatusSnapshot = buildTaskStatusSnapshot(latestUserInput, {
        request_id: requestId,
        status: 'paused',
        checkpoint_id: CHECKPOINT_ID,
        current_step_id: 'step_retrieve_1',
        latest_checkpoint: {
          checkpoint_id: CHECKPOINT_ID,
          task_id: TASK_ID,
          execution_id: EXECUTION_ID,
          status: 'paused',
          iteration_count: 1,
          completed_step_ids: [],
          latest_plan_id: PLAN_ID,
          latest_step_id: 'step_retrieve_1',
          checkpoint_reason: '用户手动暂停',
          created_at: NOW,
          metadata: {},
        },
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildSuccessEnvelope(buildActionResponse('pause', 'paused', '任务已暂停，可稍后恢复。'))),
      });
      return;
    }

    if (pathname === `/api/v1/task-runtime/tasks/${TASK_ID}/resume` && method === 'POST') {
      setSucceededSnapshot('恢复后的任务已成功完成。', '恢复执行后任务已完成，验收通过。', '恢复后执行报告');
      conversationMessages = [
        buildConversationMessage(1, 'user', latestUserInput, messageId),
        buildConversationMessage(2, 'assistant', '恢复后的任务已成功完成。', 'msg_assistant_resume'),
      ];
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildSuccessEnvelope(buildActionResponse('resume', 'running', '任务已恢复执行。'))),
      });
      return;
    }

    if (pathname === `/api/v1/task-runtime/tasks/${TASK_ID}/retry` && method === 'POST') {
      setSucceededSnapshot('重试后的任务已成功完成。', '失败任务经重试后已补齐缺口并完成。', '重试后执行报告');
      conversationMessages = [
        buildConversationMessage(1, 'user', latestUserInput, messageId),
        buildConversationMessage(2, 'assistant', '重试后的任务已成功完成。', 'msg_assistant_retry'),
      ];
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildSuccessEnvelope(buildActionResponse('retry', 'running', '任务已重新进入执行队列。'))),
      });
      return;
    }

    if (pathname === `/api/v1/task-runtime/tasks/${TASK_ID}/cancel` && method === 'POST') {
      taskStatusSnapshot = buildTaskStatusSnapshot(latestUserInput, {
        request_id: requestId,
        status: 'cancelled',
        termination: {
          status: 'cancelled',
          reason: '任务已取消。',
          final_output: null,
          metadata: {},
        },
      });
      await route.fulfill({
        status: 200,
        contentType: 'application/json; charset=utf-8',
        body: JSON.stringify(buildSuccessEnvelope(buildActionResponse('cancel', 'cancelled', '任务已取消。'))),
      });
      return;
    }

    await route.fulfill({
      status: 500,
      contentType: 'application/json; charset=utf-8',
      body: JSON.stringify({
        code: 500,
        message: `Unhandled mock route: ${method} ${pathname}`,
        error: 'MockRouteMissing',
        error_code: 'SYSTEM_MOCK_ROUTE_MISSING',
        timestamp: NOW,
      }),
    });
  });
}

test.describe('task-runtime 聊天主链路', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      window.localStorage.setItem('access_token', 'playwright-access-token');
      window.localStorage.setItem('refresh_token', 'playwright-refresh-token');
    });
  });

  test('应展示任务状态、验收报告和产物清单', async ({ page }) => {
    await registerTaskRuntimeMockRoutes(page, { streamScenario: 'success' });
    await page.goto('/');

    const input = page.getByPlaceholder('输入消息...（Shift + Enter 换行）');
    await expect(input).toBeVisible();

    await input.fill('请帮我整理需求并给出执行计划');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.getByText('任务目标与计划')).toBeVisible();
    await expect(page.getByText('任务状态')).toBeVisible();
    await expect(page.getByText('1. 检索背景信息', { exact: true })).toBeVisible();
    await expect(page.getByText('最终执行结果：已整理完成。').first()).toBeVisible();
    await expect(page.getByText('最终验收报告')).toBeVisible();
    await expect(page.getByText('复杂任务已达成目标，验收通过。')).toBeVisible();
    await expect(page.getByText('任务产物')).toBeVisible();
    await expect(page.getByText('最终执行报告')).toBeVisible();
  });

  test('prepare 失败时应回滚乐观写入的用户消息', async ({ page }) => {
    await registerTaskRuntimeMockRoutes(page, { prepareFails: true });
    await page.goto('/');

    const input = page.getByPlaceholder('输入消息...（Shift + Enter 换行）');
    await expect(input).toBeVisible();

    await input.fill('这条消息应在失败后回滚');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.getByText('知识库不存在或无权访问')).toBeVisible();
    await expect(page.locator('.message-user').filter({ hasText: '这条消息应在失败后回滚' })).toHaveCount(0);
    await expect(page.getByText('开始一段新的对话')).toBeVisible();
  });

  test('应支持暂停后恢复任务，并通过状态轮询刷新最终报告', async ({ page }) => {
    await registerTaskRuntimeMockRoutes(page, { streamScenario: 'pause_resume' });
    await page.goto('/');

    const input = page.getByPlaceholder('输入消息...（Shift + Enter 换行）');
    await input.fill('请暂停后再恢复执行');
    await page.getByRole('button', { name: '发送' }).click();

    const pauseButton = page.getByRole('button', { name: '暂停任务' });
    await expect(pauseButton).toBeVisible();
    await pauseButton.click();

    await expect(page.getByText('状态：已暂停')).toBeVisible();
    await expect(page.getByText('用户手动暂停')).toBeVisible();

    const resumeButton = page.getByRole('button', { name: '恢复任务' });
    await expect(resumeButton).toBeVisible();
    await resumeButton.click();

    await expect(page.getByText('恢复后的任务已成功完成。').first()).toBeVisible();
    await expect(page.getByText('恢复执行后任务已完成，验收通过。')).toBeVisible();
    await expect(page.getByText('恢复后执行报告')).toBeVisible();
  });

  test('失败任务应支持重试，并刷新成功终态', async ({ page }) => {
    await registerTaskRuntimeMockRoutes(page, { streamScenario: 'failure' });
    await page.goto('/');

    const input = page.getByPlaceholder('输入消息...（Shift + Enter 换行）');
    await input.fill('请模拟一个失败后再重试的任务');
    await page.getByRole('button', { name: '发送' }).click();

    await expect(page.getByRole('alert').getByText('任务执行失败：缺少关键输入。')).toBeVisible();
    const retryButton = page.getByRole('button', { name: '重试任务' });
    await expect(retryButton).toBeVisible();
    await retryButton.click();

    await expect(page.getByText('重试后的任务已成功完成。').first()).toBeVisible();
    await expect(page.getByText('失败任务经重试后已补齐缺口并完成。')).toBeVisible();
    await expect(page.getByText('重试后执行报告')).toBeVisible();
  });
});
