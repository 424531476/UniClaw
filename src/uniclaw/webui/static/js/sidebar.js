/* sidebar.js — 右侧面板(文件树、控制台、Checkpoint、Git) */

const Sidebar = {
    currentTab: 'files',
    _consoleHistory: [],
    _consoleHistoryIdx: -1,

    /** 初始化 */
    init() {
        // Tab 切换
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.onclick = () => this.switchTab(btn.dataset.tab);
        });

        // 控制台输入
        const consoleInput = document.getElementById('console-input');
        consoleInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                this._executeConsoleCommand(e.target.value);
                e.target.value = '';
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (this._consoleHistoryIdx < this._consoleHistory.length - 1) {
                    this._consoleHistoryIdx++;
                    e.target.value = this._consoleHistory[this._consoleHistory.length - 1 - this._consoleHistoryIdx];
                }
            } else if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (this._consoleHistoryIdx > 0) {
                    this._consoleHistoryIdx--;
                    e.target.value = this._consoleHistory[this._consoleHistory.length - 1 - this._consoleHistoryIdx];
                } else {
                    this._consoleHistoryIdx = -1;
                    e.target.value = '';
                }
            }
        });

        // 注册 shell_result 处理器(控制台专用)
        WS.on('shell_result', (msg) => this._onShellResult(msg));
    },

    /** 切换 Tab */
    switchTab(tab) {
        this.currentTab = tab;
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.tab === tab);
        });
        document.querySelectorAll('.tab-content').forEach(el => {
            el.classList.toggle('active', el.id === `tab-${tab}`);
        });
        // 加载对应内容
        if (tab === 'files') this._loadFileTree();
        if (tab === 'checkpoint') this._loadCheckpoints();
        if (tab === 'git') this._loadGitStatus();
        if (tab === 'console') this._loadMonitors();
    },

    /** 加载文件树 */
    async _loadFileTree() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/files?root_dir=${encodeURIComponent(rootDir)}`);
            const files = await resp.json();
            const tree = document.getElementById('file-tree');
            tree.innerHTML = files.map(f => {
                const icon = f.is_dir ? '📁' : '📄';
                return `<div class="file-tree-item ${f.is_dir ? 'dir' : 'file'}"
                    onclick="${f.is_dir ? `Sidebar._loadSubDir('${f.path}')` : `Sidebar._previewFile('${f.path}')`}">
                    ${icon} ${Utils.escapeHtml(f.name)}
                </div>`;
            }).join('');
        } catch (e) {
            console.error('加载文件树失败:', e);
        }
    },

    /** 加载子目录 */
    async _loadSubDir(path) {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/files?root_dir=${encodeURIComponent(rootDir)}&path=${encodeURIComponent(path)}`);
            const files = await resp.json();
            const tree = document.getElementById('file-tree');
            let html = `<div class="file-tree-item" onclick="Sidebar._loadFileTree()">⬅ 返回</div>`;
            html += files.map(f => {
                const icon = f.is_dir ? '📁' : '📄';
                const subPath = path + '/' + f.name;
                return `<div class="file-tree-item ${f.is_dir ? 'dir' : 'file'}"
                    onclick="${f.is_dir ? `Sidebar._loadSubDir('${subPath}')` : `Sidebar._previewFile('${subPath}')`}">
                    ${icon} ${Utils.escapeHtml(f.name)}
                </div>`;
            }).join('');
            tree.innerHTML = html;
        } catch (e) {
            console.error('加载子目录失败:', e);
        }
    },

    /** 预览文件：将 @filepath 插入到光标位置 */
    _previewFile(path) {
        const input = document.getElementById('chat-input');
        const start = input.selectionStart;
        const end = input.selectionEnd;
        const current = input.value;
        const insertText = `@${path} `;
        // 在光标位置插入,替换选中内容
        input.value = current.substring(0, start) + insertText + current.substring(end);
        // 光标移到插入内容之后
        const cursor = start + insertText.length;
        input.setSelectionRange(cursor, cursor);
        input.focus();
        // 触发 input 事件以更新高度
        input.dispatchEvent(new Event('input'));
    },

    /** 加载 Checkpoints */
    async _loadCheckpoints() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/checkpoints?root_dir=${encodeURIComponent(rootDir)}`);
            const data = await resp.json();
            const content = document.getElementById('checkpoint-content');
            const output = data.output || '';
            const checkpoints = this._parseCheckpoints(output);

            if (checkpoints.length === 0) {
                content.innerHTML = '<p style="color:var(--text-secondary);font-size:13px">无 checkpoint</p>';
                return;
            }

            let html = '<div style="font-size:12px">';
            // Combo 1: 基准
            html += '<label style="color:var(--text-secondary)">基准:</label>';
            html += '<select id="cp-from" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
            html += '<option value="current">当前</option>';
            checkpoints.forEach(cp => {
                html += `<option value="${cp.idx}">${Utils.escapeHtml(cp.label)}</option>`;
            });
            html += '</select>';
            // Combo 2: 对比
            html += '<label style="color:var(--text-secondary)">对比:</label>';
            html += '<select id="cp-to" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
            checkpoints.forEach(cp => {
                html += `<option value="${cp.idx}">${Utils.escapeHtml(cp.label)}</option>`;
            });
            html += '</select>';
            // 按钮
            html += '<div style="display:flex;gap:8px;margin-bottom:8px">';
            html += '<button class="btn-primary" onclick="Sidebar._showCheckpointDiff()" style="font-size:12px;padding:4px 12px">对比</button>';
            html += '<button class="btn-secondary" onclick="Sidebar._restoreCheckpoint()" style="font-size:12px;padding:4px 12px">恢复</button>';
            html += '</div>';
            // Diff 结果区域
            html += '<div id="cp-diff-area"></div>';
            html += '</div>';
            content.innerHTML = html;
        } catch (e) {
            console.error('加载 checkpoint 失败:', e);
        }
    },

    /** 解析 checkpoint 列表文本 */
    _parseCheckpoints(output) {
        const lines = output.split('\n').filter(l => l.trim());
        return lines.map(line => {
            const m = line.match(/^\[(\d+)\]\s+(\S+)\s+-\s+(.+)$/);
            if (m) {
                return { idx: parseInt(m[1]), name: m[2], label: `[${m[1]}] ${m[2]} - ${m[3]}` };
            }
            return null;
        }).filter(Boolean);
    },

    /** 显示 checkpoint diff */
    async _showCheckpointDiff() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const fromVal = document.getElementById('cp-from').value;
        const toVal = document.getElementById('cp-to').value;
        const diffArea = document.getElementById('cp-diff-area');
        diffArea.innerHTML = '<span style="color:var(--text-secondary)">加载中...</span>';

        try {
            const url = `/api/checkpoints/${toVal}/diff?root_dir=${encodeURIComponent(rootDir)}`;
            const resp = await fetch(url);
            const data = await resp.json();
            const diffOutput = data.output || '无差异';

            // 解析 diff 输出,提取文件列表用于筛选
            const files = this._parseDiffFiles(diffOutput);
            this._cpDiffOutput = diffOutput;
            this._cpDiffMode = 'unified';

            let html = '';
            if (files.length > 0) {
                html += '<label style="color:var(--text-secondary);font-size:11px">文件筛选:</label>';
                html += '<select id="cp-file-filter" onchange="Sidebar._filterCpDiff()" style="width:100%;padding:4px;margin:4px 0 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:12px">';
                html += '<option value="">全部文件</option>';
                files.forEach(f => { html += `<option value="${Utils.escapeHtml(f)}">${Utils.escapeHtml(f)}</option>`; });
                html += '</select>';
            }
            // Unified / Split 切换按钮
            html += '<div style="display:flex;gap:4px;margin-bottom:8px">';
            html += '<button class="btn-secondary cp-diff-btn active" onclick="Sidebar._switchCpDiffMode(\'unified\')" style="font-size:11px;padding:2px 8px">Unified</button>';
            html += '<button class="btn-secondary cp-diff-btn" onclick="Sidebar._switchCpDiffMode(\'split\')" style="font-size:11px;padding:2px 8px">Split</button>';
            html += '</div>';
            html += `<div id="cp-diff-content">${this._renderCpDiff(diffOutput, 'unified')}</div>`;
            diffArea.innerHTML = html;
        } catch (e) {
            diffArea.innerHTML = `<span style="color:#ef4444">加载失败: ${e.message}</span>`;
        }
    },

    /** 切换 checkpoint diff 视图模式 */
    _switchCpDiffMode(mode) {
        this._cpDiffMode = mode;
        document.querySelectorAll('.cp-diff-btn').forEach(b => b.classList.remove('active'));
        event.target.classList.add('active');
        const filter = document.getElementById('cp-file-filter')?.value || '';
        const diffContent = document.getElementById('cp-diff-content');
        diffContent.innerHTML = this._renderCpDiff(this._cpDiffOutput || '', mode, filter);
    },

    /** 渲染 checkpoint diff(支持 unified 和 split 模式) */
    _renderCpDiff(diffOutput, mode, fileFilter) {
        if (mode === 'split') {
            // Split 模式：解析 unified diff 并转为 split 视图
            return this._renderSplitDiff(diffOutput, fileFilter);
        }
        return this._renderUnifiedDiff(diffOutput, fileFilter);
    },

    /** 渲染 split diff(从 unified diff 解析) */
    _renderSplitDiff(diffOutput, fileFilter) {
        const lines = diffOutput.split('\n');
        let html = '<div style="display:flex;gap:4px;font-size:11px">';
        let leftLines = [], rightLines = [];
        let inFile = !fileFilter;

        for (const line of lines) {
            if (line.startsWith('diff --git')) {
                const m = line.match(/b\/(.+)$/);
                const fname = m ? m[1] : '';
                inFile = !fileFilter || fname === fileFilter;
                if (inFile && (leftLines.length > 0 || rightLines.length > 0)) {
                    html += this._renderSplitPair(leftLines, rightLines);
                    leftLines = []; rightLines = [];
                }
                continue;
            }
            if (!inFile) continue;
            if (line.startsWith('@@')) {
                if (leftLines.length > 0 || rightLines.length > 0) {
                    html += this._renderSplitPair(leftLines, rightLines);
                    leftLines = []; rightLines = [];
                }
                html += `<div style="width:100%;color:#a78bfa;padding:2px 4px;font-size:10px">${Utils.escapeHtml(line)}</div>`;
                continue;
            }
            if (line.startsWith('+')) {
                rightLines.push({ text: line, type: 'add' });
            } else if (line.startsWith('-')) {
                leftLines.push({ text: line, type: 'del' });
            } else {
                leftLines.push({ text: line, type: 'ctx' });
                rightLines.push({ text: line, type: 'ctx' });
            }
        }
        if (leftLines.length > 0 || rightLines.length > 0) {
            html += this._renderSplitPair(leftLines, rightLines);
        }
        html += '</div>';
        return html;
    },

    /** 渲染 split diff 的左右两栏 */
    _renderSplitPair(leftLines, rightLines) {
        const maxLen = Math.max(leftLines.length, rightLines.length);
        let leftHtml = '<div style="flex:1;background:var(--bg-primary);border-radius:4px;padding:4px;overflow-x:auto">';
        let rightHtml = '<div style="flex:1;background:var(--bg-primary);border-radius:4px;padding:4px;overflow-x:auto">';
        for (let i = 0; i < maxLen; i++) {
            const l = leftLines[i];
            const r = rightLines[i];
            if (l) {
                const color = l.type === 'del' ? '#f87171' : l.type === 'add' ? '#4ade80' : 'inherit';
                leftHtml += `<div style="color:${color};white-space:pre">${Utils.escapeHtml(l.text)}</div>`;
            }
            if (r) {
                const color = r.type === 'add' ? '#4ade80' : r.type === 'del' ? '#f87171' : 'inherit';
                rightHtml += `<div style="color:${color};white-space:pre">${Utils.escapeHtml(r.text)}</div>`;
            }
        }
        leftHtml += '</div>';
        rightHtml += '</div>';
        return leftHtml + rightHtml;
    },

    /** 解析 diff 输出中的文件列表 */
    _parseDiffFiles(diffOutput) {
        const files = [];
        diffOutput.split('\n').forEach(line => {
            const m = line.match(/^diff --git a\/(.+?) b\//);
            if (m && !files.includes(m[1])) files.push(m[1]);
        });
        return files;
    },

    /** 按文件筛选 diff */
    _filterCpDiff() {
        const filter = document.getElementById('cp-file-filter').value;
        const diffContent = document.getElementById('cp-diff-content');
        const mode = this._cpDiffMode || 'unified';
        diffContent.innerHTML = this._renderCpDiff(this._cpDiffOutput || '', mode, filter);
    },

    /** 渲染 unified diff 输出(带颜色) */
    _renderUnifiedDiff(diffOutput, fileFilter) {
        const lines = diffOutput.split('\n');
        let html = '<pre style="font-size:11px;white-space:pre-wrap;background:var(--bg-primary);padding:8px;border-radius:4px;max-height:300px;overflow-y:auto;margin:0">';
        let inFile = !fileFilter;
        for (const line of lines) {
            // 文件分隔线
            if (line.startsWith('diff --git')) {
                const m = line.match(/b\/(.+)$/);
                const fname = m ? m[1] : '';
                inFile = !fileFilter || fname === fileFilter;
                if (inFile) html += `<span style="color:#60a5fa;font-weight:bold">${Utils.escapeHtml(line)}\n</span>`;
                continue;
            }
            if (!inFile) continue;
            if (line.startsWith('---') || line.startsWith('+++')) {
                html += `<span style="color:#60a5fa">${Utils.escapeHtml(line)}\n</span>`;
            } else if (line.startsWith('@@')) {
                html += `<span style="color:#a78bfa">${Utils.escapeHtml(line)}\n</span>`;
            } else if (line.startsWith('+')) {
                html += `<span style="color:#4ade80">${Utils.escapeHtml(line)}\n</span>`;
            } else if (line.startsWith('-')) {
                html += `<span style="color:#f87171">${Utils.escapeHtml(line)}\n</span>`;
            } else {
                html += Utils.escapeHtml(line) + '\n';
            }
        }
        html += '</pre>';
        return html;
    },

    /** 恢复到选中的 checkpoint */
    async _restoreCheckpoint() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const cpIdx = document.getElementById('cp-to').value;
        if (cpIdx === 'current') {
            Utils.showToast('请选择一个 checkpoint 进行恢复');
            return;
        }
        const confirmed = await Utils.confirm(`确定恢复到 checkpoint [${cpIdx}]？当前未保存的更改将丢失。`);
        if (!confirmed) return;
        try {
            Utils.showLoading('正在恢复 checkpoint...');
            const resp = await fetch(`/api/checkpoints/${cpIdx}/restore`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir }),
            });
            if (!resp.ok) {
                const error = await resp.json().catch(() => ({ detail: '恢复失败' }));
                throw new Error(error.detail);
            }
            Utils.showToast('恢复成功');
            this._loadCheckpoints();
        } catch (e) {
            console.error('恢复 checkpoint 失败:', e);
            Utils.showError(e.message || '恢复失败');
        } finally {
            Utils.hideLoading();
        }
    },

    /** 加载 Git 状态 */
    async _loadGitStatus() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        try {
            const resp = await fetch(`/api/git/status?root_dir=${encodeURIComponent(rootDir)}`);
            const data = await resp.json();
            const content = document.getElementById('git-content');
            const lines = (data.output || '').split('\n').filter(l => l.trim());
            if (lines.length === 0) {
                content.innerHTML = '<p style="color:var(--text-secondary);font-size:13px">无变更</p>';
                return;
            }
            let html = '<div style="margin-bottom:8px"><button class="btn-text" onclick="Sidebar._aiCommit()" title="AI 生成 commit">✨</button></div>';
            html += '<div style="margin-bottom:8px"><textarea id="git-commit-msg" rows="3" placeholder="提交信息..." style="width:100%;padding:4px 8px;background:var(--bg-primary);border:1px solid var(--border);border-radius:4px;color:var(--text-primary);font-size:13px;resize:vertical"></textarea></div>';
            html += '<div style="margin-bottom:8px"><button class="btn-primary" onclick="Sidebar._gitCommit()" style="font-size:12px">提交</button></div>';
            html += lines.map(line => {
                const statusCode = line.substring(0, 2);
                const file = line.substring(3);
                // X = index status, Y = worktree status
                const indexStatus = statusCode[0];
                const worktreeStatus = statusCode[1];
                const isStaged = indexStatus !== ' ' && indexStatus !== '?';
                const isUntracked = statusCode === '??';
                const icon = isUntracked ? '❓' : isStaged ? '✅' : '📝';
                const stagedClass = isStaged ? 'staged' : 'unstaged';
                return `<div style="padding:2px 0;font-size:13px;display:flex;align-items:center;gap:6px">
                    <input type="checkbox" class="git-file ${stagedClass}" value="${Utils.escapeHtml(file)}" ${isStaged ? 'checked' : ''} onchange="Sidebar._toggleStage(this)" />
                    ${icon} ${Utils.escapeHtml(file)}
                </div>`;
            }).join('');
            content.innerHTML = html;
        } catch (e) {
            console.error('加载 git 状态失败:', e);
        }
    },

    /** 切换文件暂存状态 */
    async _toggleStage(checkbox) {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;
        const file = checkbox.value;
        const endpoint = checkbox.checked ? '/api/git/stage' : '/api/git/unstage';
        try {
            await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir, files: [file] }),
            });
        } catch (e) {
            Utils.showToast('操作失败');
            checkbox.checked = !checkbox.checked;
        }
    },

    /** Git 提交 */
    async _gitCommit() {
        const rootDir = SessionPanel.activeProjectDir;
        const msg = document.getElementById('git-commit-msg')?.value;
        if (!rootDir || !msg) return;
        const files = Array.from(document.querySelectorAll('.git-file:checked')).map(el => el.value);
        try {
            const resp = await fetch('/api/git/commit', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir, message: msg, files }),
            });
            const data = await resp.json();
            Utils.showToast('提交成功');
            this._loadGitStatus();
        } catch (e) {
            Utils.showToast('提交失败');
        }
    },

    /** AI 生成 commit 信息 */
    async _aiCommit() {
        const rootDir = SessionPanel.activeProjectDir;
        if (!rootDir) return;

        const btn = event?.target;
        if (btn) { btn.disabled = true; btn.textContent = '⏳'; }

        try {
            const resp = await fetch('/api/git/ai-commit-message', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ root_dir: rootDir }),
            });
            const data = await resp.json();

            if (data.error) {
                Utils.showToast(data.error);
                return;
            }

            const input = document.getElementById('git-commit-msg');
            if (input && data.message) {
                input.value = data.message;
                input.focus();
            }
        } catch (e) {
            Utils.showToast('AI 生成失败: ' + e.message);
        } finally {
            if (btn) { btn.disabled = false; btn.textContent = '✨'; }
        }
    },

    /** 执行控制台命令 */
    _executeConsoleCommand(cmd) {
        if (!cmd.trim()) return;
        const sessionId = SessionPanel.activeSessionId;
        if (!sessionId) {
            this._appendConsoleOutput('错误: 未选择会话\n', 'error');
            return;
        }
        // 记录命令历史
        this._consoleHistory.push(cmd);
        this._consoleHistoryIdx = -1;
        // 显示命令
        this._appendConsoleOutput(`$ ${cmd}\n`, 'command');
        // 通过 WebSocket 发送 shell 命令
        WS.send({ type: 'shell', session_id: sessionId, command: cmd, source: 'console' });
    },

    /** 收到 shell 命令结果 */
    _onShellResult(msg) {
        // 只显示来自控制台的结果(非聊天框 ! 命令)
        if (msg.source !== 'console') return;
        const output = msg.output || '';
        if (output.trim()) {
            this._appendConsoleOutput(output + '\n', 'result');
        }
        if (!msg.success) {
            this._appendConsoleOutput('(命令执行失败)\n', 'error');
        }
    },

    /** 追加控制台输出 */
    _appendConsoleOutput(text, type) {
        const output = document.getElementById('console-output');
        const span = document.createElement('span');
        span.className = `console-${type}`;
        span.textContent = text;
        output.appendChild(span);
        output.scrollTop = output.scrollHeight;
    },

    /** 加载后台进程列表 */
    async _loadMonitors() {
        try {
            const resp = await fetch('/api/monitors');
            const monitors = await resp.json();
            const container = document.getElementById('console-output');
            // 移除旧的进程列表
            container.querySelectorAll('.monitor-item').forEach(el => el.remove());
            if (monitors.length === 0) return;
            const header = document.createElement('div');
            header.className = 'monitor-item';
            header.style.cssText = 'padding:4px 0;font-size:12px;color:var(--text-secondary);border-top:1px solid var(--border);margin-top:8px';
            header.textContent = '后台进程:';
            container.appendChild(header);
            monitors.forEach(m => {
                const el = document.createElement('div');
                el.className = 'monitor-item';
                el.style.cssText = 'padding:2px 0;font-size:12px;display:flex;align-items:center;gap:8px';
                const statusIcon = m.status === 'running' ? '▶' : '⏹';
                el.innerHTML = `<span>${statusIcon} ${Utils.escapeHtml(m.description || m.command)}</span>`;
                if (m.status === 'running') {
                    const stopBtn = document.createElement('button');
                    stopBtn.className = 'btn-text';
                    stopBtn.style.cssText = 'font-size:11px;padding:1px 6px;color:#ef4444';
                    stopBtn.textContent = 'STOP';
                    stopBtn.onclick = () => this._stopMonitor(m.id);
                    el.appendChild(stopBtn);
                }
                container.appendChild(el);
            });
        } catch (e) {
            console.error('加载进程列表失败:', e);
        }
    },

    /** 停止后台进程 */
    async _stopMonitor(monitorId) {
        try {
            await fetch(`/api/monitors/${monitorId}/stop`, { method: 'POST' });
            Utils.showToast('进程已停止');
            this._loadMonitors();
        } catch (e) {
            Utils.showToast('停止失败');
        }
    },
};
