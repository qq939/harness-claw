const { WebSocketServer } = require('ws');
const { spawn } = require('child_process');
const crypto = require('crypto');
const http = require('http');

const PORT = process.env.PORT || 8080;
const DOCKER_HOST = process.env.DOCKER_HOST || 'host.docker.internal';
const SSH_USER = process.env.SSH_USER || 'agent';
const SSH_PASS = process.env.SSH_PASS || 'agent';
// WS 鉴权 token：与 control / obs 用同一个 WS_TOKEN，未设置时回退到 agent。
const WS_TOKEN = process.env.WS_TOKEN || 'agent';

// 定长比较，避免按字符试探出正确 token
function tokenOk(provided) {
    if (!WS_TOKEN || !provided) return false;
    const a = Buffer.from(String(provided));
    const b = Buffer.from(WS_TOKEN);
    if (a.length !== b.length) return false;
    return crypto.timingSafeEqual(a, b);
}

const server = http.createServer((req, res) => {
    if (req.url === '/health') {
        res.writeHead(200);
        res.end('OK');
        return;
    }
    res.writeHead(404);
    res.end('Not found');
});

const wss = new WebSocketServer({ server });

wss.on('connection', (ws, req) => {
    const url = new URL(req.url, `http://localhost`);

    // token 鉴权：没有正确 token 的连接一律拒绝，不启动 SSH 隧道。
    if (!tokenOk(url.searchParams.get('token'))) {
        console.log('WS connection rejected: invalid token');
        ws.close(4401, 'invalid token');
        return;
    }

    const targetPort = url.searchParams.get('port');

    if (!targetPort) {
        ws.close(4000, 'Missing port parameter');
        return;
    }

    const sshPort = parseInt(targetPort);
    console.log(`SSH connection requested for port ${sshPort}`);

    const proc = spawn('sshpass', [
        '-p', SSH_PASS,
        'ssh', '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=/dev/null',
        '-tt',
        '-p', String(sshPort),
        `${SSH_USER}@${DOCKER_HOST}`
    ], {
        stdio: ['pipe', 'pipe', 'pipe']
    });

    proc.on('error', (err) => {
        console.error('SSH process error:', err.message);
        ws.close(4001, err.message);
    });

    proc.stdout.on('data', (data) => {
        if (ws.readyState === ws.OPEN) {
            ws.send(data.toString());
        }
    });

    proc.stderr.on('data', (data) => {
        if (ws.readyState === ws.OPEN) {
            ws.send(data.toString());
        }
    });

    proc.on('close', (code) => {
        console.log(`SSH process closed with code ${code}`);
        if (ws.readyState === ws.OPEN) {
            ws.close(1000, `Process exited with code ${code}`);
        }
    });

    ws.on('message', (msg) => {
        proc.stdin.write(msg.toString());
    });

    ws.on('close', () => {
        proc.kill();
    });

    ws.on('error', () => {
        proc.kill();
    });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`SSH Gateway running on port ${PORT}`);
});
