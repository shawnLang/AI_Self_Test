import express from 'express';
import cors from 'cors';
import db from './db.js';

const app = express();
const port = 3001;

const IMAGE_EXTENSIONS = new Set(['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg']);
const VIDEO_EXTENSIONS = new Set(['mp4', 'mov', 'avi', 'mkv', 'webm', 'flv', 'm4v']);

const resolveMediaInfo = (clientApiUrl, item) => {
  const rawFileUrl = String(item?.fileUrl || '').trim();
  const normalizedFileUrl = rawFileUrl.replace(/^\/+/, '');
  const rawName = String(item?.name || '').trim();
  const explicitExt = String(item?.fileExtension || '').toLowerCase();
  const inferredExtFromFileUrl = normalizedFileUrl.includes('.') ? normalizedFileUrl.split('.').pop().toLowerCase() : '';
  const inferredExtFromName = rawName.includes('.') ? rawName.split('.').pop().toLowerCase() : '';
  const inferredExt = inferredExtFromFileUrl || inferredExtFromName;
  const extension = explicitExt || inferredExt;

  let mediaType = 'unknown';
  if (IMAGE_EXTENSIONS.has(extension)) mediaType = 'image';
  if (VIDEO_EXTENSIONS.has(extension)) mediaType = 'video';

  try {
    const parsed = new URL(clientApiUrl);
    const mediaUrl = normalizedFileUrl ? `${parsed.origin}/weed/${normalizedFileUrl}` : null;
    return { mediaType, mediaUrl };
  } catch {
    return { mediaType, mediaUrl: null };
  }
};

const safeJson = async (response) => {
  const rawText = await response.text();
  try {
    return JSON.parse(rawText);
  } catch {
    return { rawText };
  }
};

const trimTrailingSlash = (value = '') => String(value || '').trim().replace(/\/+$/, '');
const normalizeEndpointUrl = (value = '') => trimTrailingSlash(value);

const buildAuthHeaders = (apiKey) => ({
  'Content-Type': 'application/json',
  'Authorization': `Bearer ${apiKey}`,
  'X-API-Key': apiKey,
  'api-key': apiKey
});

const buildModelListCandidates = (endpointUrl) => {
  const normalized = trimTrailingSlash(endpointUrl)
    .replace(/\/chat\/completions$/i, '')
    .replace(/\/responses$/i, '')
    .replace(/\/models$/i, '');

  const candidates = new Set();
  if (!normalized) return [];

  if (normalized.endsWith('/v1')) {
    candidates.add(`${normalized}/models`);
    candidates.add(`${normalized.replace(/\/v1$/, '')}/models`);
  } else {
    candidates.add(`${normalized}/v1/models`);
    candidates.add(`${normalized}/models`);
  }

  return Array.from(candidates);
};

const buildChatCompletionCandidates = (endpointUrl) => {
  const normalized = trimTrailingSlash(endpointUrl);
  if (!normalized) return [];
  if (/\/chat\/completions$/i.test(normalized)) return [normalized];

  const base = normalized
    .replace(/\/models$/i, '')
    .replace(/\/responses$/i, '');

  const candidates = new Set();
  if (base.endsWith('/v1')) {
    candidates.add(`${base}/chat/completions`);
  }
  candidates.add(`${base}/v1/chat/completions`);
  candidates.add(`${base}/chat/completions`);

  return Array.from(candidates);
};

const extractDetectedModels = (resultData) => {
  const sourceLists = [
    resultData?.data,
    resultData?.models,
    resultData?.results,
    resultData?.items
  ].filter(Array.isArray);

  const names = sourceLists.flatMap((list) => list.map((item) => String(item?.id || item?.name || item?.model || '').trim()));

  if (names.length === 0 && typeof resultData?.model === 'string') {
    names.push(String(resultData.model).trim());
  }

  return Array.from(new Set(names.filter(Boolean)));
};

const detectRemoteModels = async (endpointUrl, apiKey) => {
  const candidates = buildModelListCandidates(endpointUrl);
  const errors = [];

  for (const url of candidates) {
    try {
      const response = await fetch(url, {
        method: 'GET',
        headers: buildAuthHeaders(apiKey)
      });
      const resultData = await safeJson(response);
      if (!response.ok) {
        errors.push(`${url}: ${resultData?.error?.message || resultData?.message || `HTTP ${response.status}`}`);
        continue;
      }

      const models = extractDetectedModels(resultData);
      if (models.length > 0) {
        return { models, detectedUrl: url };
      }

      errors.push(`${url}: 未识别到模型列表`);
    } catch (error) {
      errors.push(`${url}: ${error.message}`);
    }
  }

  throw new Error(errors[0] || '无法自动检索模型列表');
};

const parseAssistantMessage = (resultData) => {
  const messageContent = resultData?.choices?.[0]?.message?.content;
  if (typeof messageContent === 'string') return messageContent.trim();
  if (Array.isArray(messageContent)) {
    return messageContent
      .map((part) => typeof part?.text === 'string' ? part.text : '')
      .join('\n')
      .trim();
  }

  if (typeof resultData?.output_text === 'string') return resultData.output_text.trim();
  if (Array.isArray(resultData?.output)) {
    return resultData.output
      .flatMap((item) => Array.isArray(item?.content) ? item.content : [])
      .map((part) => typeof part?.text === 'string' ? part.text : '')
      .join('\n')
      .trim();
  }

  return '';
};

const parseDataUrlBase64 = (dataUrl = '') => {
  const match = String(dataUrl).match(/^data:([^;]+);base64,(.+)$/);
  if (!match) return null;
  return { mimeType: match[1], base64Data: match[2] };
};

const buildAttachmentParts = (attachments = []) => {
  return attachments.flatMap((attachment) => {
    const name = String(attachment?.name || '未命名附件').trim();
    const mimeType = String(attachment?.mimeType || attachment?.type || 'application/octet-stream').trim();
    const textContent = String(attachment?.textContent || '').trim();
    const dataUrl = String(attachment?.dataUrl || '').trim();

    if (mimeType.startsWith('image/') && dataUrl) {
      return [{ type: 'image_url', image_url: { url: dataUrl } }];
    }

    if (mimeType.startsWith('audio/') && dataUrl) {
      const parsedAudio = parseDataUrlBase64(dataUrl);
      if (parsedAudio) {
        const format = parsedAudio.mimeType.split('/')[1] || 'mp3';
        return [{ type: 'input_audio', input_audio: { data: parsedAudio.base64Data, format } }];
      }
    }

    if (textContent) {
      return [{
        type: 'text',
        text: `附件《${name}》内容如下：\n${textContent.slice(0, 12000)}`
      }];
    }

    return [{
      type: 'text',
      text: `用户上传了附件《${name}》，类型为 ${mimeType}。当前接口按通用兼容模式发送，请结合附件信息回答。`
    }];
  });
};

const normalizeChatMessages = (messages = []) => {
  return messages
    .filter((message) => ['system', 'user', 'assistant'].includes(message?.role))
    .map((message) => {
      if (message.role !== 'user') {
        return {
          role: message.role,
          content: String(message.content || '')
        };
      }

      const text = String(message.content || '').trim();
      const attachmentParts = buildAttachmentParts(Array.isArray(message.attachments) ? message.attachments : []);
      const contentParts = [];

      if (text) {
        contentParts.push({ type: 'text', text });
      }
      contentParts.push(...attachmentParts);

      return {
        role: 'user',
        content: contentParts.length > 0 ? contentParts : [{ type: 'text', text: '请查看附件并回答。' }]
      };
    });
};

const chatWithMultimodalModel = async (modelConfig, messages) => {
  const candidates = buildChatCompletionCandidates(modelConfig.endpoint_url);
  const normalizedMessages = normalizeChatMessages(messages);
  const errors = [];

  for (const url of candidates) {
    try {
      const response = await fetch(url, {
        method: 'POST',
        headers: buildAuthHeaders(modelConfig.api_key),
        body: JSON.stringify({
          model: modelConfig.model_name,
          messages: normalizedMessages,
          temperature: 0.2,
          max_tokens: 1200
        })
      });

      const resultData = await safeJson(response);
      if (!response.ok) {
        errors.push(`${url}: ${resultData?.error?.message || resultData?.message || `HTTP ${response.status}`}`);
        continue;
      }

      const assistantMessage = parseAssistantMessage(resultData);
      if (assistantMessage) {
        return { assistantMessage, requestUrl: url, raw: resultData };
      }

      errors.push(`${url}: 模型已响应，但未返回可解析文本`);
    } catch (error) {
      errors.push(`${url}: ${error.message}`);
    }
  }

  throw new Error(errors[0] || '多模态模型调用失败');
};

const mapMultimodalModelRow = (row) => ({
  id: row.id,
  modelName: row.model_name,
  endpointUrl: row.endpoint_url,
  apiKey: row.api_key,
  status: row.status || 'active',
  detectedModels: (() => {
    try {
      return JSON.parse(row.detected_models_json || '[]');
    } catch {
      return [];
    }
  })(),
  lastDetectedAt: row.last_detected_at,
  createdAt: row.created_at,
  updatedAt: row.updated_at
});

const OMLX_API_URL = process.env.OMLX_API_URL || 'http://192.168.1.116:8888/v1/chat/completions';
const OMLX_API_KEY = process.env.OMLX_API_KEY || '8888';
const OMLX_MODEL = process.env.OMLX_MODEL || 'gemma-4-e4b-it-8bit';

const runningTaskIds = new Set();

const ensureTaskDefaultModelRegistered = () => {
  const endpointUrl = normalizeEndpointUrl(OMLX_API_URL);
  const apiKey = String(OMLX_API_KEY || '').trim();
  const modelName = String(OMLX_MODEL || '').trim();

  if (!endpointUrl || !apiKey || !modelName) {
    return;
  }

  const now = new Date().toISOString();
  const existing = db.prepare(`
    SELECT *
    FROM multimodal_models
    WHERE endpoint_url = ? AND model_name = ?
    LIMIT 1
  `).get(endpointUrl, modelName);

  if (existing) {
    let detectedModels = [];
    try {
      detectedModels = JSON.parse(existing.detected_models_json || '[]');
    } catch {
      detectedModels = [];
    }

    const mergedDetectedModels = Array.from(new Set([...detectedModels, modelName]));
    db.prepare(`
      UPDATE multimodal_models
      SET api_key = ?,
          status = 'active',
          detected_models_json = ?,
          last_detected_at = COALESCE(last_detected_at, ?),
          updated_at = ?
      WHERE id = ?
    `).run(
      apiKey,
      JSON.stringify(mergedDetectedModels),
      now,
      now,
      existing.id
    );
    return;
  }

  db.prepare(`
    INSERT INTO multimodal_models (
      model_name, endpoint_url, api_key, status, detected_models_json, last_detected_at, created_at, updated_at
    ) VALUES (?, ?, ?, 'active', ?, ?, ?, ?)
  `).run(
    modelName,
    endpointUrl,
    apiKey,
    JSON.stringify([modelName]),
    now,
    now,
    now
  );
};

const mapTaskRow = (task) => {
  const total = Number(task.total_count || 0);
  const processed = Number(task.processed_count || 0);
  const progress = total > 0
    ? Math.min(100, Math.round((processed / total) * 100))
    : task.execution_status === 'completed' ? 100 : 0;

  let filters = null;
  try {
    filters = task.filters_json ? JSON.parse(task.filters_json) : null;
  } catch {
    filters = null;
  }

  return {
    ...task,
    clientId: task.client_id,
    autoConfirm: Boolean(task.auto_confirm),
    active: Boolean(task.active),
    executionMode: task.execution_mode || 'manual',
    filters,
    totalCount: total,
    processedCount: processed,
    executionStatus: task.execution_status || 'idle',
    progress
  };
};

const sanitizeTaskFilters = (rawFilters = {}) => {
  const filters = rawFilters && typeof rawFilters === 'object' ? rawFilters : {};
  const classifyList = Array.isArray(filters.classifyList)
    ? filters.classifyList.map(Number).filter((value) => Number.isFinite(value))
    : [];

  const normalized = {
    classifyList,
    keyword: String(filters.keyword || '').trim(),
    spName: String(filters.spName || '').trim(),
    startTime: String(filters.startTime || '').trim(),
    endTime: String(filters.endTime || '').trim(),
    fileBmp: filters.fileBmp === undefined || filters.fileBmp === null || filters.fileBmp === '' ? 'all' : String(filters.fileBmp),
    uploadType: filters.uploadType === undefined || filters.uploadType === null || filters.uploadType === '' ? 'all' : String(filters.uploadType),
    idType: filters.idType === undefined || filters.idType === null || filters.idType === '' ? 'all' : String(filters.idType),
    size: Number(filters.size) > 0 ? Number(filters.size) : 50,
    current: Number(filters.current) > 0 ? Number(filters.current) : 1
  };

  return normalized;
};

const buildTaskSearchBody = (filters = {}) => {
  const normalized = sanitizeTaskFilters(filters);
  const searchBody = {
    size: normalized.size,
    current: normalized.current
  };

  if (normalized.keyword) searchBody.keyword = normalized.keyword;
  if (normalized.spName) searchBody.spName = normalized.spName;
  if (normalized.classifyList.length > 0) searchBody.classifyList = normalized.classifyList;
  if (normalized.startTime) searchBody.startTime = `${normalized.startTime} 00:00:00`;
  if (normalized.endTime) searchBody.endTime = `${normalized.endTime} 23:59:59`;
  if (normalized.fileBmp !== 'all') searchBody.fileBmp = [Number(normalized.fileBmp)];
  if (normalized.uploadType !== 'all') searchBody.uploadType = [Number(normalized.uploadType)];
  if (normalized.idType !== 'all') searchBody.idType = Number(normalized.idType);

  return searchBody;
};

const buildOriginalResult = (item) => {
  const species = String(item?.spNameList || '').trim();
  return species || '未识别物种';
};

const fetchTaskQueryResults = async (taskId, rawFilters = {}) => {
  const task = db.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId);
  if (!task) throw new Error('Task not found');

  const client = db.prepare('SELECT * FROM clients WHERE id = ?').get(task.client_id);
  if (!client) throw new Error('Client not found');

  let savedFilters = {};
  try {
    savedFilters = task.filters_json ? JSON.parse(task.filters_json) : {};
  } catch {
    savedFilters = {};
  }

  const searchBody = buildTaskSearchBody({
    ...savedFilters,
    ...(rawFilters || {})
  });

  let accessToken = client.access_token;
  const now = Date.now();

  const requestDataPage = async (token, withBearer = false) => {
    const dataRes = await fetch(`${client.apiUrl}/openApi/icFile/findFilePage`, {
      method: 'POST',
      headers: {
        'Authorization': withBearer ? `Bearer ${token}` : token,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(searchBody)
    });

    const resultData = await safeJson(dataRes);
    return { dataRes, resultData };
  };

  const loginAndUpdateToken = async () => {
    const authRes = await fetch(`${client.apiUrl}/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ userName: client.account, password: client.password, clientType: 'WEB' })
    });
    const authData = await safeJson(authRes);

    if (!authData.accessToken) {
      throw new Error('Login failed to client API');
    }

    accessToken = authData.accessToken;
    db.prepare('UPDATE clients SET access_token = ?, refresh_token = ?, expires_in = ? WHERE id = ?')
      .run(authData.accessToken, authData.refreshToken, authData.expiresIn || now + 86400000, client.id);
  };

  if (!accessToken || !client.expires_in || now > client.expires_in - 3600 * 1000) {
    let isRefreshed = false;

    if (client.refresh_token) {
      try {
        const authRes = await fetch(`${client.apiUrl}/auth/refresh`, {
          method: 'POST',
          headers: { 'Authorization': client.refresh_token, 'Content-Type': 'application/json' }
        });
        const authData = await safeJson(authRes);
        if (authData.accessToken) {
          accessToken = authData.accessToken;
          db.prepare('UPDATE clients SET access_token = ?, refresh_token = ?, expires_in = ? WHERE id = ?')
            .run(authData.accessToken, authData.refreshToken, authData.expiresIn || now + 86400000, client.id);
          isRefreshed = true;
        }
      } catch (e) {
        console.error('Refresh failed, falling back to login', e.message);
      }
    }

    if (!isRefreshed) {
      await loginAndUpdateToken();
    }
  }

  let { dataRes, resultData } = await requestDataPage(accessToken, false);
  const tokenError = dataRes.status === 401 || String(resultData?.message || '').includes('token');

  if (tokenError) {
    await loginAndUpdateToken();
    ({ dataRes, resultData } = await requestDataPage(accessToken, false));
  }

  if (dataRes.status === 401) {
    ({ dataRes, resultData } = await requestDataPage(accessToken, true));
  }

  const mappedResults = Array.isArray(resultData?.results)
    ? resultData.results.map(item => {
      const mediaInfo = resolveMediaInfo(client.apiUrl, item);
      return {
        ...item,
        mediaType: mediaInfo.mediaType,
        mediaUrl: mediaInfo.mediaUrl
      };
    })
    : [];

  return {
    task,
    client,
    dataRes,
    resultData,
    results: mappedResults
  };
};

const parseModelContent = (resultData) => {
  const content = resultData?.choices?.[0]?.message?.content;
  if (typeof content === 'string') return content.trim();
  if (Array.isArray(content)) {
    return content
      .map(part => (typeof part?.text === 'string' ? part.text : ''))
      .join('\n')
      .trim();
  }
  return '';
};

const normalizeSpeciesLabel = (rawSpecies) => {
  const text = String(rawSpecies || '').trim();
  if (!text) return '无';

  const lower = text.toLowerCase();
  if (['none', 'null', 'no', 'empty', 'unknown', '无法判断', '未识别', '无', '没有'].includes(lower)) {
    return '无';
  }
  if (lower === 'person' || lower === 'human' || lower === 'people' || lower === 'man' || lower === 'woman') {
    return '人';
  }
  return text.slice(0, 60);
};

const normalizeAiResult = (rawText) => {
  const text = String(rawText || '').trim();
  if (!text) return '无';

  const jsonMatch = text.match(/\{[\s\S]*\}/);
  if (jsonMatch) {
    try {
      const parsed = JSON.parse(jsonMatch[0]);
      const species = String(parsed.species || parsed.result || parsed.name || '').trim();
      return normalizeSpeciesLabel(species);
    } catch (e) {
      // Ignore parsing fallback.
    }
  }

  const cleaned = text
    .replace(/^最可能物种[:：]\s*/i, '')
    .replace(/^species[:：]\s*/i, '')
    .split('\n')[0]
    .trim();

  return normalizeSpeciesLabel(cleaned);
};

const buildModelMessageContent = (item) => {
  const mediaUrl = item?.mediaUrl || '';
  const mediaType = item?.mediaType || 'unknown';
  const coverUrl = item?.coverUrl || '';
  const pieces = [
    {
      type: 'text',
      text: [
        '你是一个动物分类专家，请根据媒体内容识别最可能的一个动物。',
        '物种范围包含人类；如果画面里没有可识别物种，请返回“无”。',
        '只返回一行 JSON，不要返回其他文字：{"species":"物种名或无"}',
        `媒体类型: ${mediaType}`,
        `媒体地址: ${mediaUrl || '无'}`
      ].join('\n')
    }
  ];

  if (mediaType === 'image' && mediaUrl) {
    pieces.push({ type: 'image_url', image_url: { url: mediaUrl } });
  } else if (mediaType === 'video') {
    if (coverUrl) {
      pieces.push({ type: 'image_url', image_url: { url: coverUrl } });
    }
  }

  return pieces;
};

const callOmlxRecognition = async (item) => {
  const response = await fetch(OMLX_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Authorization': `Bearer ${OMLX_API_KEY}`
    },
    body: JSON.stringify({
      model: OMLX_MODEL,
      messages: [{ role: 'user', content: buildModelMessageContent(item) }],
      temperature: 0.1,
      max_tokens: 180
    })
  });

  const resultData = await safeJson(response);
  if (!response.ok) {
    const errText = resultData?.error?.message || resultData?.message || `HTTP ${response.status}`;
    throw new Error(`oMLX 调用失败: ${errText}`);
  }
  return normalizeAiResult(parseModelContent(resultData));
};

const processTaskExecution = async (taskId, selectedItems) => {
  const task = db.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId);
  if (!task) {
    runningTaskIds.delete(taskId);
    return;
  }

  const nowIso = new Date().toISOString();
  const total = selectedItems.length;
  db.prepare(`
    UPDATE tasks
    SET active = 1,
        execution_status = 'running',
        total_count = ?,
        processed_count = 0,
        started_at = ?,
        finished_at = NULL,
        last_error = NULL
    WHERE id = ?
  `).run(total, nowIso, taskId);

  let processed = 0;
  try {
    for (const item of selectedItems) {
      let aiResult = '';
      try {
        aiResult = await callOmlxRecognition(item);
      } catch (error) {
        aiResult = `识别失败: ${error.message}`;
      }

      const reviewId = `T${taskId}-F${item?.id || 'NA'}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const imageUrl = item?.mediaUrl || item?.coverUrl || 'about:blank';
      const reviewStatus = 'pending';

      db.prepare(`
        INSERT INTO reviews (
          id, image_url, original_result, sp_name_list, ai_result, status,
          task_id, task_name, file_id, media_type, media_url, file_time, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      `).run(
        reviewId,
        imageUrl,
        buildOriginalResult(item),
        String(item?.spNameList || '').trim() || null,
        aiResult,
        reviewStatus,
        taskId,
        task.name,
        item?.id || null,
        item?.mediaType || null,
        item?.mediaUrl || null,
        item?.fileTime || null,
        new Date().toISOString()
      );

      processed += 1;
      db.prepare('UPDATE tasks SET processed_count = ? WHERE id = ?').run(processed, taskId);
    }

    db.prepare(`
      UPDATE tasks
      SET active = 0,
          execution_status = 'completed',
          processed_count = ?,
          finished_at = ?
      WHERE id = ?
    `).run(processed, new Date().toISOString(), taskId);
  } catch (error) {
    db.prepare(`
      UPDATE tasks
      SET active = 0,
          execution_status = 'failed',
          last_error = ?,
          finished_at = ?
      WHERE id = ?
    `).run(error.message, new Date().toISOString(), taskId);
  } finally {
    runningTaskIds.delete(taskId);
  }
};

app.use(cors());
app.use(express.json({ limit: '50mb' }));

// === Clients API ===
app.get('/api/clients', (req, res) => {
  try {
    const clients = db.prepare('SELECT * FROM clients').all();
    res.json(clients);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/clients', (req, res) => {
  const { name, apiUrl, account, password, status } = req.body;
  try {
    const stmt = db.prepare('INSERT INTO clients (name, apiUrl, account, password, status) VALUES (?, ?, ?, ?, ?)');
    const info = stmt.run(name, apiUrl, account, password || '', status || '活跃');
    res.json({ id: info.lastInsertRowid, name, apiUrl, account, status: status || '活跃' });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.put('/api/clients/:id', (req, res) => {
  const { name, apiUrl, account, password, status } = req.body;
  try {
    const stmt = db.prepare('UPDATE clients SET name = ?, apiUrl = ?, account = ?, password = ?, status = ? WHERE id = ?');
    stmt.run(name, apiUrl, account, password || '', status || '活跃', req.params.id);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.delete('/api/clients/:id', (req, res) => {
  try {
    // Delete related tasks first
    db.prepare('DELETE FROM tasks WHERE client_id = ?').run(req.params.id);
    db.prepare('DELETE FROM clients WHERE id = ?').run(req.params.id);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// === Multimodal Models API ===
app.get('/api/multimodal-models', (req, res) => {
  try {
    ensureTaskDefaultModelRegistered();
    const rows = db.prepare(`
      SELECT *
      FROM multimodal_models
      ORDER BY datetime(updated_at) DESC, id DESC
    `).all();

    res.json(rows.map(mapMultimodalModelRow));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/multimodal-models/detect', async (req, res) => {
  const { endpointUrl, apiKey } = req.body || {};

  if (!String(endpointUrl || '').trim() || !String(apiKey || '').trim()) {
    return res.status(400).json({ error: '请先输入地址和密码。' });
  }

  try {
    const result = await detectRemoteModels(endpointUrl, apiKey);
    res.json({
      models: result.models,
      detectedUrl: result.detectedUrl,
      recommendedModel: result.models[0] || ''
    });
  } catch (error) {
    res.status(400).json({ error: error.message });
  }
});

app.post('/api/multimodal-models', (req, res) => {
  const { modelName, endpointUrl, apiKey, status, detectedModels } = req.body || {};
  const now = new Date().toISOString();

  if (!String(modelName || '').trim() || !String(endpointUrl || '').trim() || !String(apiKey || '').trim()) {
    return res.status(400).json({ error: '模型名称、地址、密码不能为空。' });
  }

  try {
    const info = db.prepare(`
      INSERT INTO multimodal_models (
        model_name, endpoint_url, api_key, status, detected_models_json, last_detected_at, created_at, updated_at
      ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `).run(
      String(modelName).trim(),
      normalizeEndpointUrl(endpointUrl),
      String(apiKey).trim(),
      status || 'active',
      JSON.stringify(Array.isArray(detectedModels) ? detectedModels : []),
      Array.isArray(detectedModels) && detectedModels.length > 0 ? now : null,
      now,
      now
    );

    const row = db.prepare('SELECT * FROM multimodal_models WHERE id = ?').get(info.lastInsertRowid);
    res.json(mapMultimodalModelRow(row));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.put('/api/multimodal-models/:id', (req, res) => {
  const { modelName, endpointUrl, apiKey, status, detectedModels } = req.body || {};
  const now = new Date().toISOString();

  if (!String(modelName || '').trim() || !String(endpointUrl || '').trim() || !String(apiKey || '').trim()) {
    return res.status(400).json({ error: '模型名称、地址、密码不能为空。' });
  }

  try {
    db.prepare(`
      UPDATE multimodal_models
      SET model_name = ?,
          endpoint_url = ?,
          api_key = ?,
          status = ?,
          detected_models_json = ?,
          last_detected_at = ?,
          updated_at = ?
      WHERE id = ?
    `).run(
      String(modelName).trim(),
      normalizeEndpointUrl(endpointUrl),
      String(apiKey).trim(),
      status || 'active',
      JSON.stringify(Array.isArray(detectedModels) ? detectedModels : []),
      Array.isArray(detectedModels) && detectedModels.length > 0 ? now : null,
      now,
      req.params.id
    );

    const row = db.prepare('SELECT * FROM multimodal_models WHERE id = ?').get(req.params.id);
    res.json(mapMultimodalModelRow(row));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.delete('/api/multimodal-models/:id', (req, res) => {
  try {
    db.prepare('DELETE FROM multimodal_models WHERE id = ?').run(req.params.id);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/multimodal-models/:id/chat', async (req, res) => {
  const { messages } = req.body || {};

  if (!Array.isArray(messages) || messages.length === 0) {
    return res.status(400).json({ error: '请至少输入一条对话消息。' });
  }

  try {
    const modelConfig = db.prepare('SELECT * FROM multimodal_models WHERE id = ?').get(req.params.id);
    if (!modelConfig) {
      return res.status(404).json({ error: '未找到对应的多模态模型配置。' });
    }

    const result = await chatWithMultimodalModel(modelConfig, messages);
    res.json({
      reply: result.assistantMessage,
      modelName: modelConfig.model_name,
      usedUrl: result.requestUrl
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// === Tasks API ===
app.get('/api/tasks', (req, res) => {
  try {
    const tasks = db.prepare(`
      SELECT tasks.*, clients.name as clientName 
      FROM tasks 
      LEFT JOIN clients ON tasks.client_id = clients.id
    `).all();
    
    const mapped = tasks.map(mapTaskRow);
    
    res.json(mapped);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/tasks/:id', (req, res) => {
  try {
    const task = db.prepare(`
      SELECT tasks.*, clients.name as clientName
      FROM tasks
      LEFT JOIN clients ON tasks.client_id = clients.id
      WHERE tasks.id = ?
    `).get(req.params.id);

    if (!task) {
      return res.status(404).json({ error: 'Task not found' });
    }

    res.json(mapTaskRow(task));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/tasks', (req, res) => {
  const { name, clientId, interval, threshold, filters, autoConfirm, active, executionMode } = req.body;
  try {
    const normalizedFilters = sanitizeTaskFilters(filters);
    const stmt = db.prepare(`
      INSERT INTO tasks (name, client_id, interval, threshold, filters_json, execution_mode, auto_confirm, active)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    `);
    const info = stmt.run(
      name,
      clientId,
      interval,
      Number.isFinite(Number(threshold)) ? Number(threshold) : 0,
      JSON.stringify(normalizedFilters),
      executionMode === 'auto' ? 'auto' : 'manual',
      autoConfirm ? 1 : 0,
      active ? 1 : 0
    );
    res.json({ id: info.lastInsertRowid });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.delete('/api/tasks/:id', (req, res) => {
  try {
    db.prepare('DELETE FROM reviews WHERE task_id = ?').run(req.params.id);
    db.prepare('DELETE FROM tasks WHERE id = ?').run(req.params.id);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Update task status
app.put('/api/tasks/:id/status', (req, res) => {
  const { active } = req.body;
  try {
    if (active) {
      db.prepare("UPDATE tasks SET active = 1, execution_status = 'running' WHERE id = ?").run(req.params.id);
    } else {
      db.prepare(`
        UPDATE tasks
        SET active = 0,
            execution_status = CASE WHEN execution_status = 'running' THEN 'paused' ELSE execution_status END
        WHERE id = ?
      `).run(req.params.id);
    }
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Proxy to fetch data from Client API
app.post('/api/tasks/:id/query-data', async (req, res) => {
  const taskId = req.params.id;

  try {
    const { dataRes, resultData, results } = await fetchTaskQueryResults(taskId, req.body || {});

    if (Array.isArray(resultData?.results)) {
      return res.status(dataRes.status).json({ ...resultData, results });
    }

    res.status(dataRes.status).json(resultData);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.post('/api/tasks/:id/run-now', async (req, res) => {
  const taskId = Number(req.params.id);

  try {
    const task = db.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId);
    if (!task) {
      return res.status(404).json({ error: 'Task not found' });
    }

    if (runningTaskIds.has(taskId) || task.execution_status === 'running') {
      return res.status(409).json({ error: '当前任务正在执行，请稍后再试' });
    }

    const { results } = await fetchTaskQueryResults(taskId, req.body || {});
    const executionItems = results.map(item => ({
      id: item.id,
      name: item.name,
      spNameList: item.spNameList,
      classify: item.classify,
      fileTime: item.fileTime,
      fileUrl: item.fileUrl,
      coverUrl: item.coverUrl,
      mediaType: item.mediaType,
      mediaUrl: item.mediaUrl
    }));

    if (executionItems.length === 0) {
      return res.status(400).json({ error: '当前任务按筛选条件未查询到可执行的数据' });
    }

    runningTaskIds.add(taskId);
    void processTaskExecution(taskId, executionItems);

    res.json({
      success: true,
      message: '任务已开始立即执行',
      total: executionItems.length
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Execute task with selected data
app.post('/api/tasks/:id/execute', async (req, res) => {
  const taskId = Number(req.params.id);
  const { selectedItems, fileIds } = req.body;
  try {
    const task = db.prepare('SELECT * FROM tasks WHERE id = ?').get(taskId);
    if (!task) {
      return res.status(404).json({ error: 'Task not found' });
    }

    if (runningTaskIds.has(taskId) || task.execution_status === 'running') {
      return res.status(409).json({ error: '当前任务正在执行，请稍后再试' });
    }

    let executionItems = Array.isArray(selectedItems) ? selectedItems : [];
    if (executionItems.length === 0 && Array.isArray(fileIds) && fileIds.length > 0) {
      executionItems = fileIds.map(id => ({ id }));
    }
    if (executionItems.length === 0) {
      return res.status(400).json({ error: '未收到可执行的文件数据' });
    }

    runningTaskIds.add(taskId);
    void processTaskExecution(taskId, executionItems);

    res.json({
      success: true,
      message: '任务已开始执行',
      total: executionItems.length
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// === Reviews API ===
app.get('/api/reviews', (req, res) => {
  try {
    const taskId = Number(req.query.taskId);
    const status = String(req.query.status || 'pending');
    const params = [status];
    let sql = 'SELECT * FROM reviews WHERE status = ?';
    if (Number.isFinite(taskId) && taskId > 0) {
      sql += ' AND task_id = ?';
      params.push(taskId);
    }
    sql += ' ORDER BY datetime(created_at) DESC, id DESC';

    const items = db.prepare(sql).all(...params);
    const mapped = items.map(item => ({
      id: item.id,
      imageUrl: item.image_url,
      originalResult: String(item.sp_name_list || '').trim() || item.original_result,
      aiResult: item.ai_result,
      status: item.status,
      taskId: item.task_id,
      taskName: item.task_name,
      mediaType: item.media_type || 'image',
      mediaUrl: item.media_url || item.image_url,
      fileTime: item.file_time
    }));
    res.json(mapped);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

app.get('/api/reviews/completed-tasks', (req, res) => {
  try {
    const tasks = db.prepare(`
      SELECT id, name, total_count, processed_count, finished_at
      FROM tasks
      WHERE execution_status = 'completed'
        AND total_count > 0
        AND processed_count >= total_count
      ORDER BY datetime(finished_at) DESC, id DESC
    `).all();
    res.json(tasks.map(task => ({
      id: task.id,
      name: task.name,
      totalCount: task.total_count,
      processedCount: task.processed_count,
      progress: 100,
      finishedAt: task.finished_at
    })));
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Delete a single review (Confirming basically removes it from pending view)
app.delete('/api/reviews/:id', (req, res) => {
  try {
    db.prepare('DELETE FROM reviews WHERE id = ?').run(req.params.id);
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Confirm multiple reviews
app.post('/api/reviews/confirm', (req, res) => {
  const { ids } = req.body; // array
  try {
    if(ids && ids.length > 0) {
      const placeholders = ids.map(() => '?').join(',');
      db.prepare(`UPDATE reviews SET status = 'confirmed' WHERE id IN (${placeholders})`).run(...ids);
    }
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// Delete multiple reviews
app.post('/api/reviews/delete', (req, res) => {
  const { ids } = req.body; // array
  try {
    if(ids && ids.length > 0) {
      const placeholders = ids.map(() => '?').join(',');
      db.prepare(`DELETE FROM reviews WHERE id IN (${placeholders})`).run(...ids);
    }
    res.json({ success: true });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

// === Dashboard API ===
app.get('/api/dashboard/stats', (req, res) => {
  try {
    const activeTasks = db.prepare("SELECT COUNT(*) AS count FROM tasks WHERE execution_status = 'running'").get().count;
    const pendingReviews = db.prepare("SELECT COUNT(*) AS count FROM reviews WHERE status = 'pending'").get().count;
    const processedToday = db.prepare(`
      SELECT COUNT(*) AS count
      FROM reviews
      WHERE created_at IS NOT NULL
        AND DATE(created_at, 'localtime') = DATE('now', 'localtime')
    `).get().count;
    const anomalies = db.prepare("SELECT COUNT(*) AS count FROM tasks WHERE execution_status = 'failed'").get().count;
    const recentActivities = db.prepare(`
      SELECT id, name, execution_status, processed_count, total_count, finished_at
      FROM tasks
      WHERE finished_at IS NOT NULL
      ORDER BY datetime(finished_at) DESC
      LIMIT 8
    `).all().map(task => ({
      id: task.id,
      name: task.name,
      status: task.execution_status,
      processedCount: task.processed_count,
      totalCount: task.total_count,
      finishedAt: task.finished_at
    }));
    
    res.json({
      activeTasks,
      processedToday,
      pendingReviews,
      anomalies,
      recentActivities
    });
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
});

ensureTaskDefaultModelRegistered();

app.listen(port, () => {
  console.log(`Backend server running on http://localhost:${port}`);
});
