// hermit-llm-gateway
//
// 统一的大模型出口：所有云端 api key 只存在这一份，卡片容器不再各自持有。
//
// 提供两类接口：
//   1) Anthropic 协议透传（<前缀>/v1/messages 等）：卡片里的 claude CLI 把
//      ANTHROPIC_BASE_URL 指向本服务（如 http://<本服务>/minimax），用 token=agent
//      鉴权；本服务按路径前缀（无前缀时按模型名）挑出对应上游，换上真正的
//      api key 转发，支持 SSE 流式。
//   2) /ask/claude：与各卡片 server.js 同款的问答接口，方便不方便跑 claude CLI
//      的调用方直接提问。
//
// 鉴权：所有接口都要求 token（query 参数 / Authorization 头 / x-api-key 头），
//      默认 agent。本服务只挂在内网，不发布宿主机端口，不对公网开放。

const http = require('http');
const fs = require('fs');
const crypto = require('crypto');
const { Readable } = require('stream');

const PORT = Number(process.env.PORT || 8083);
const HOST = process.env.HOST || '0.0.0.0';
const TOKEN = process.env.LLM_GATEWAY_TOKEN || 'agent';
const CONFIG_PATH = process.env.UPSTREAMS_FILE || '/agent-config/upstreams.json';

// 配置文件热加载：改完 key 不必重启服务
let cached = { mtimeMs: 0, data: null };

function loadConfig() {
    let stat;
    try {
        stat = fs.statSync(CONFIG_PATH);
    } catch (e) {
        console.error(`[llm-gateway] 配置文件不存在: ${CONFIG_PATH}`);
        return { upstreams: {} };
    }
    if (cached.data && cached.mtimeMs === stat.mtimeMs) {
        return cached.data;
    }
    try {
        const data = JSON.parse(fs.readFileSync(CONFIG_PATH, 'utf8'));
        cached = { mtimeMs: stat.mtimeMs, data };
        console.log('[llm-gateway] 已加载上游配置');
        return data;
    } catch (e) {
        console.error(`[llm-gateway] 配置文件解析失败: ${e.message}`);
        return { upstreams: {} };
    }
}

// 上游名 -> 上游定义；同时展开 aliases（同一上游可以有多个路径前缀）
function upstreamIndex() {
    const cfg = loadConfig();
    const upstreams = cfg.upstreams || {};
    const index = {};
    for (const [name, def] of Object.entries(upstreams)) {
        index[name] = { name, def };
        for (const alias of def.aliases || []) {
            index[alias] = { name, def };
        }
    }
    return { cfg, upstreams, index };
}

// 按模型名找上游。找不到对应模型时退回默认上游，并把模型名换成该上游的主模型，
// 免得把上游不认识的模型名原样发过去换来一个 400。
function pickByModel(model) {
    const { cfg, upstreams } = upstreamIndex();
    const names = Object.keys(upstreams);
    if (!names.length) return null;

    if (model) {
        for (const name of names) {
            const models = upstreams[name].models || [];
            if (models.includes(model)) {
                return { name, def: upstreams[name], model };
            }
        }
    }
    const fallbackName = (cfg.default_upstream && upstreams[cfg.default_upstream])
        ? cfg.default_upstream
        : names[0];
    return { name: fallbackName, def: upstreams[fallbackName], model: '' };
}

// 上游不认识请求里的模型名时，换成它自己的主模型
function fitModel(def, model) {
    const models = def.models || [];
    if (model && models.includes(model)) return model;
    return models[0] || model || '';
}

function tokenOk(provided) {
    if (!TOKEN || !provided) return false;
    const a = Buffer.from(String(provided));
    const b = Buffer.from(TOKEN);
    if (a.length !== b.length) return false;
    return crypto.timingSafeEqual(a, b);
}

// token 可以放在 query（?token=）、Authorization 头或 x-api-key 头
function extractToken(req, url) {
    const q = url.searchParams.get('token');
    if (q) return q;
    const auth = req.headers['authorization'];
    if (auth && /^Bearer\s+/i.test(auth)) return auth.replace(/^Bearer\s+/i, '').trim();
    const apiKey = req.headers['x-api-key'];
    if (apiKey) return apiKey;
    return '';
}

function send(res, status, body, contentType) {
    res.writeHead(status, {
        'Content-Type': contentType || 'application/json; charset=utf-8',
        'Cache-Control': 'no-store',
    });
    res.end(body);
}

function readBody(req) {
    return new Promise((resolve, reject) => {
        const chunks = [];
        req.on('data', (c) => chunks.push(c));
        req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
        req.on('error', reject);
    });
}

// 题目既可以是明文，也可以是 base64（与各卡片 server.js 的约定一致）
function decodeQuestion(raw) {
    if (!raw) return null;
    if (raw.includes(' ') || raw.length < 50) {
        try {
            return decodeURIComponent(raw);
        } catch (e) {
            return raw;
        }
    }
    try {
        return Buffer.from(raw, 'base64').toString('utf8');
    } catch (e) {
        return null;
    }
}

// 拆出路径前缀：/minimax/v1/messages -> { prefix: 'minimax', rest: '/v1/messages' }
// 没有已知前缀时 prefix 为空，交给按模型名路由。
function splitPrefix(pathname) {
    const { index } = upstreamIndex();
    const m = /^\/([^/]+)(\/.*)?$/.exec(pathname);
    if (m && index[m[1]]) {
        return { prefix: m[1], rest: m[2] || '/' };
    }
    return { prefix: '', rest: pathname };
}

// Anthropic 协议透传：选上游、换上真 key、流式回传
async function forwardAnthropic(req, res, url) {
    const body = await readBody(req);
    let requestedModel = '';
    try {
        const parsed = JSON.parse(body || '{}');
        if (parsed.model) requestedModel = parsed.model;
    } catch (e) {
        // 解析不了就按默认上游走
    }

    const { prefix, rest } = splitPrefix(url.pathname);
    const { index } = upstreamIndex();

    let picked;
    if (prefix) {
        picked = { name: index[prefix].name, def: index[prefix].def };
    } else {
        picked = pickByModel(requestedModel);
    }
    if (!picked) {
        send(res, 503, JSON.stringify({
            error: { type: 'upstream_unavailable', message: '没有可用的上游配置' },
        }));
        return;
    }
    const { def } = picked;
    const model = fitModel(def, requestedModel);

    // 模型名对不上上游时，替换成上游认识的名字
    let outBody = body;
    if (model && model !== requestedModel) {
        try {
            const parsed = JSON.parse(body || '{}');
            parsed.model = model;
            outBody = JSON.stringify(parsed);
        } catch (e) {
            outBody = body;
        }
    }

    const target = def.base_url.replace(/\/+$/, '') + rest;
    // 两个鉴权头都要换成真 key：Claude Code CLI 用 ANTHROPIC_AUTH_TOKEN 时
    // 发的是 Authorization: Bearer <token>，原样转发会把本地 token 送到上游。
    const headers = {
        'content-type': req.headers['content-type'] || 'application/json',
        'anthropic-version': req.headers['anthropic-version'] || '2023-06-01',
        'x-api-key': def.api_key,
        'authorization': 'Bearer ' + def.api_key,
    };
    // 透传 beta 头（Claude Code CLI 会带）
    if (req.headers['anthropic-beta']) headers['anthropic-beta'] = req.headers['anthropic-beta'];

    const controller = new AbortController();
    req.on('close', () => controller.abort());

    let upstreamRes;
    try {
        upstreamRes = await fetch(target, {
            method: req.method,
            headers,
            body: req.method === 'GET' || req.method === 'HEAD' ? undefined : outBody,
            signal: controller.signal,
        });
    } catch (e) {
        if (controller.signal.aborted) return;
        send(res, 502, JSON.stringify({ error: { type: 'upstream_error', message: e.message } }));
        return;
    }

    const outHeaders = {
        'Content-Type': upstreamRes.headers.get('content-type') || 'application/json',
        'Cache-Control': 'no-store',
    };
    const reqId = upstreamRes.headers.get('x-request-id');
    if (reqId) outHeaders['x-request-id'] = reqId;
    res.writeHead(upstreamRes.status, outHeaders);

    // 流式回传：Claude Code CLI 用 SSE，必须边收边发，不能整体缓冲
    if (upstreamRes.body) {
        const stream = Readable.fromWeb(upstreamRes.body);
        stream.on('error', () => { try { res.end(); } catch (e) {} });
        stream.pipe(res);
    } else {
        res.end();
    }
}

// /ask/claude：把一次提问转成上游的一次 messages 调用，返回纯文本
async function handleAsk(req, res, url) {
    let question = url.searchParams.get('q');
    if (!question && req.method === 'POST') {
        const body = await readBody(req);
        try {
            const parsed = JSON.parse(body || '{}');
            question = parsed.q || body;
        } catch (e) {
            question = body;
        }
    }
    const decoded = decodeQuestion(question);
    if (!decoded) {
        send(res, 400, JSON.stringify({ error: 'missing or invalid q parameter' }));
        return;
    }

    const { index } = upstreamIndex();
    const want = url.searchParams.get('upstream') || '';
    const requestedModel = url.searchParams.get('model') || '';

    let picked;
    if (want && index[want]) {
        picked = { name: index[want].name, def: index[want].def };
    } else {
        picked = pickByModel(requestedModel);
    }
    if (!picked) {
        send(res, 503, JSON.stringify({ error: '没有可用的上游配置' }));
        return;
    }
    const { def } = picked;
    const model = fitModel(def, requestedModel);

    const target = def.base_url.replace(/\/+$/, '') + '/v1/messages';
    const payload = {
        model: model,
        max_tokens: Number(url.searchParams.get('max_tokens') || 4096),
        messages: [{ role: 'user', content: decoded }],
    };

    let upstreamRes;
    try {
        upstreamRes = await fetch(target, {
            method: 'POST',
            headers: {
                'content-type': 'application/json',
                'anthropic-version': '2023-06-01',
                'x-api-key': def.api_key,
            },
            body: JSON.stringify(payload),
        });
    } catch (e) {
        send(res, 502, JSON.stringify({ error: e.message }));
        return;
    }

    const raw = await upstreamRes.text();
    if (!upstreamRes.ok) {
        send(res, upstreamRes.status, raw);
        return;
    }
    let text = '';
    try {
        const parsed = JSON.parse(raw);
        text = (parsed.content || []).map((c) => (c && c.text) || '').join('');
    } catch (e) {
        text = raw;
    }
    send(res, 200, text, 'text/plain; charset=utf-8');
}

const server = http.createServer(async (req, res) => {
    let url;
    try {
        url = new URL(req.url, `http://localhost:${PORT}`);
    } catch (e) {
        send(res, 400, JSON.stringify({ error: 'bad request url' }));
        return;
    }

    if (url.pathname === '/health') {
        const { upstreams } = upstreamIndex();
        send(res, 200, JSON.stringify({ ok: true, upstreams: Object.keys(upstreams) }));
        return;
    }

    if (!tokenOk(extractToken(req, url))) {
        send(res, 401, JSON.stringify({ error: 'unauthorized' }));
        return;
    }

    if (url.pathname === '/ask/claude') {
        await handleAsk(req, res, url);
        return;
    }

    // Anthropic 协议：/v1/messages、/<前缀>/v1/messages 等
    if (url.pathname.startsWith('/v1/') || /^\/[^/]+\/v1\//.test(url.pathname)) {
        await forwardAnthropic(req, res, url);
        return;
    }

    send(res, 404, JSON.stringify({ error: 'not found' }));
});

server.listen(PORT, HOST, () => {
    console.log(`[llm-gateway] listening on http://${HOST}:${PORT}`);
    console.log(`[llm-gateway] upstream config: ${CONFIG_PATH}`);
});
