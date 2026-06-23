/* chat.js — 聊天区组件 */

const Chat = {
    currentSessionId: null,
    streamingEl: null,     // 当前流式输出的 .msg-content 容器
    streamingContent: '',  // 流式内容累积
    streamingBody: null,   // 流式 markdown-body 元素
    thinkingEl: null,
    thinkingContent: '',
    toolBlocks: {},        // tool_call_id → DOM element(用于关联 tool 结果)
    _historyData: null,    // 完整历史消息
    _compactData: null,    // 压缩后消息
    _currentView: 'history',

    /** 初始化 */
    init() {
        // 绑定历史/压缩消息切换按钮
        document.getElementById('history-toggle')?.addEventListener('click', () => {
            const nextView = this._currentView === 'history' ? 'compact' : 'history';
            this._switchView(nextView);
        });

        WS.on('session_created', (msg) => this._onSessionCreated(msg));
        WS.on('user', (msg) => this._onUser(msg));
        WS.on('thinking_start', () => this._onThinkingStart());
        WS.on('thinking', (msg) => this._onThinking(msg));
        WS.on('text', (msg) => this._onText(msg));
        WS.on('assistant', (msg) => this._onAssistant(msg));
        WS.on('tool_preparing', (msg) => this._onToolPreparing(msg));
        WS.on('tool_start', (msg) => this._onToolStart(msg));
        WS.on('tool_end', (msg) => this._onToolEnd(msg));
        WS.on('config_changed', (msg) => this._onConfigChanged(msg));
        WS.on('end', (msg) => this._onEnd(msg));
        WS.on('error', (msg) => this._onError(msg));
        WS.on('interrupted', (msg) => this._onInterrupted(msg));
        WS.on('shell_result', (msg) => this._onShellResult(msg));
        WS.on('command_output', (msg) => this._onCommandOutput(msg));
        WS.on('command_result', (msg) => this._onCommandResult(msg));
        WS.on('system_message', (msg) => this._onSystemMessage(msg));
        WS.on('spinner_start', (msg) => this._onSpinner(msg));
        WS.on('spinner_update', (msg) => this._onSpinner(msg));
        WS.on('spinner_stop', (msg) => this._onSpinnerStop(msg));
    },

    // ============================================================
    //  历史消息回放
    // ============================================================

    /** 加载历史消息 */
    async loadHistory(sessionId) {
        this.currentSessionId = sessionId;
        this.toolBlocks = {};
        this._historyData = null;
        this._compactData = null;
        try {
            Utils.showLoading('加载历史消息...');
            const resp = await fetch(`/api/sessions/${sessionId}`);
            if (!resp.ok) {
                const err = await resp.json().catch(() => ({ detail: resp.statusText }));
                this.clear();
                this._appendSystemMessage(`加载失败: ${err.detail || resp.statusText}`);
                Utils.showError(`加载失败: ${err.detail || resp.statusText}`);
                return;
            }
            const data = await resp.json();
            this._historyData = data.history || null;
            this._compactData = data.messages || null;
            // 有压缩差异时显示切换按钮
            const toggle = document.getElementById('history-toggle');
            const hasDiff = this._historyData && this._compactData
                && this._historyData.length !== this._compactData.length;
            if (toggle) {
                toggle.style.display = hasDiff ? '' : 'none';
                toggle.textContent = '📜';
                toggle.title = '当前: 完整历史 (点击切换压缩)';
            }
            // 默认显示历史消息
            this._currentView = 'history';
            this._renderCurrentView();
            // 加载 todolist(从 config 获取)
            this._fetchAndRenderTodolist(sessionId);
        } catch (e) {
            console.error('加载历史失败:', e);
            this.clear();
            this._appendSystemMessage(`加载失败: ${e.message}`);
            Utils.showError(`加载失败: ${e.message}`);
        } finally {
            Utils.hideLoading();
        }
    },

    /** 切换历史/压缩消息视图 */
    _switchView(view) {
        if (view === this._currentView) return;
        this._currentView = view;
        // 更新按钮图标
        const btn = document.getElementById('history-toggle');
        if (btn) {
            btn.textContent = view === 'history' ? '📜' : '📦';
            btn.title = view === 'history' ? '当前: 完整历史 (点击切换压缩)' : '当前: 压缩消息 (点击切换完整)';
        }
        this._renderCurrentView();
    },

    /** 渲染当前视图 */
    _renderCurrentView() {
        const container = document.getElementById('chat-messages');
        container.innerHTML = '';
        const messages = this._currentView === 'history' ? this._historyData : this._compactData;
        if (messages && messages.length > 0) {
            this._replayMessages(messages);
        } else {
            this._appendSystemMessage('新会话,发送消息开始对话');
        }
        MsgNav?.refresh?.();
        this._scrollToBottom();
    },

    /** 回放消息列表(与 TUI replay_messages 逻辑一致) */
    _replayMessages(messages) {
        // 先收集 tool_call_id → tool result 的映射
        const toolResults = {};
        messages.forEach(msg => {
            if (msg.role === 'tool' && msg.tool_call_id) {
                toolResults[msg.tool_call_id] = msg;
            }
        });

        messages.forEach(msg => {
            const role = msg.role;
            if (role === 'system') {
                // 系统消息：灰色居中
                this._appendSystemMessage(this._extractText(msg.content));
            } else if (role === 'user') {
                const text = this._extractText(msg.content);
                const images = this._extractImages(msg.content);
                // [system] 前缀的消息显示为灰色系统消息(如 sleep_timer 唤醒)
                if (text.startsWith('[system]')) {
                    if (text.includes('(用户执行Shell命令)')) {
                        this._appendShellResultFromHistory(text);
                    } else if (images.length > 0) {
                        this._appendSystemMessageWithImages(text, images);
                    } else {
                        this._appendSystemMessage(text);
                    }
                } else if (images.length > 0) {
                    this._appendUserMessageWithImages(text, images);
                } else {
                    this._appendUserMessage(text);
                }
            } else if (role === 'assistant') {
                const el = this._appendAssistantMessage('');
                const body = el.querySelector('.markdown-body');

                // 渲染思考内容(放在消息内容上方)
                if (msg.reasoning_content) {
                    this._appendThinkingBlock(el, msg.reasoning_content, true, body);
                }

                // _appendAssistantMessage 已创建 .markdown-body,直接填充内容
                if (body && msg.content) {
                    body.innerHTML = Utils.renderMarkdown(msg.content);
                    this._addCopyButtons(body);
                }

                // 渲染工具调用
                if (msg.tool_calls && msg.tool_calls.length > 0) {
                    msg.tool_calls.forEach(tc => {
                        const tcId = tc.id || '';
                        const name = tc.function ? tc.function.name : (tc.name || 'tool');
                        const args = tc.function ? tc.function.arguments : (tc.arguments || '{}');
                        // 查找对应的 tool result
                        const result = toolResults[tcId];
                        const resultContent = result ? this._extractText(result.content) : null;
                        const success = result ? !(resultContent && resultContent.startsWith('[TOOL_ERROR]')) : null;
                        this._appendToolBlock(el, name, args, resultContent, success, tcId);
                    });
                }
                // 显示 usage 信息
                const usage = msg.usage || {};
                this._appendUsageInfo(el, usage.input_tokens, usage.output_tokens, msg.model_name);
            }
            // tool role 不单独显示,已关联到 assistant 的工具调用块中
        });
    },

    // ============================================================
    //  消息创建
    // ============================================================

    /** 清空聊天区 */
    clear() {
        document.getElementById('chat-messages').innerHTML = '';
        this._resetStreamingState();
        this.toolBlocks = {};
        const todoArea = document.getElementById('todolist-area');
        if (todoArea) todoArea.style.display = 'none';
    },

    /** 追加系统消息 */
    _appendSystemMessage(content) {
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message system';
        el.textContent = content;
        container.appendChild(el);
        this._scrollToBottom();
        return el;
    },

    /** 追加带图片的系统消息 */
    _appendSystemMessageWithImages(content, imageUrls) {
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message system with-images';
        // 文字在上
        if (content) {
            const textEl = document.createElement('div');
            textEl.textContent = content;
            el.appendChild(textEl);
        }
        // 图片在下
        const imgGrid = document.createElement('div');
        imgGrid.className = 'msg-image-grid';
        imageUrls.forEach(url => {
            const img = document.createElement('img');
            img.src = url;
            img.className = 'msg-image-thumb';
            img.onclick = () => this._showImageOverlay(url);
            imgGrid.appendChild(img);
        });
        el.appendChild(imgGrid);
        container.appendChild(el);
        this._scrollToBottom();
        return el;
    },

    /** 追加用户消息(右侧气泡 + 头像) */
    _appendUserMessage(content) {
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message user';

        const row = document.createElement('div');
        row.className = 'msg-row';

        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.innerHTML = '<svg><use href="#avatar-user"/></svg>';

        const bubble = document.createElement('div');
        bubble.className = 'msg-bubble';
        // 支持 Markdown 渲染(换行、加粗、代码等)
        const body = document.createElement('div');
        body.className = 'markdown-body';
        body.innerHTML = Utils.renderMarkdown(content);
        this._addCopyButtons(body);
        bubble.appendChild(body);

        row.appendChild(avatar);
        row.appendChild(bubble);
        el.appendChild(row);
        container.appendChild(el);
        this._scrollToBottom();
        return el;
    },

    /** 追加带图片的用户消息(图片在气泡上方) */
    _appendUserMessageWithImages(content, imageUrls) {
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message user';

        // 图片区(气泡上方,右对齐)
        const imgGrid = document.createElement('div');
        imgGrid.className = 'msg-image-grid';
        imageUrls.forEach(url => {
            const img = document.createElement('img');
            img.src = url;
            img.className = 'msg-image-thumb';
            img.onclick = () => this._showImageOverlay(url);
            imgGrid.appendChild(img);
        });
        el.appendChild(imgGrid);

        // 文字气泡行
        if (content) {
            const row = document.createElement('div');
            row.className = 'msg-row';

            const avatar = document.createElement('div');
            avatar.className = 'msg-avatar';
            avatar.innerHTML = '<svg><use href="#avatar-user"/></svg>';

            const bubble = document.createElement('div');
            bubble.className = 'msg-bubble';
            const body = document.createElement('div');
            body.className = 'markdown-body';
            body.innerHTML = Utils.renderMarkdown(content);
            this._addCopyButtons(body);
            bubble.appendChild(body);

            row.appendChild(avatar);
            row.appendChild(bubble);
            el.appendChild(row);
        }

        container.appendChild(el);
        this._scrollToBottom();
        return el;
    },

    /** 在最后一个 user 消息的气泡上方追加图片 */
    _appendImagesToLastUserMessage(imageUrls) {
        const container = document.getElementById('chat-messages');
        const userMsgs = container.querySelectorAll('.message.user');
        if (userMsgs.length === 0) return;
        const lastMsg = userMsgs[userMsgs.length - 1];
        // 查找已有的图片网格,或在 msg-row 之前新建
        let imgGrid = lastMsg.querySelector('.msg-image-grid');
        if (!imgGrid) {
            imgGrid = document.createElement('div');
            imgGrid.className = 'msg-image-grid';
            const msgRow = lastMsg.querySelector('.msg-row');
            if (msgRow) {
                lastMsg.insertBefore(imgGrid, msgRow);
            } else {
                lastMsg.appendChild(imgGrid);
            }
        }
        imageUrls.forEach(url => {
            const img = document.createElement('img');
            img.src = url;
            img.className = 'msg-image-thumb';
            img.onclick = () => this._showImageOverlay(url);
            imgGrid.appendChild(img);
        });
        this._scrollToBottom();
    },

    /** 全屏图片预览 */
    _showImageOverlay(url) {
        const overlay = document.createElement('div');
        overlay.className = 'image-overlay';
        overlay.onclick = () => overlay.remove();
        const img = document.createElement('img');
        img.src = url;
        overlay.appendChild(img);
        document.body.appendChild(overlay);
    },

    /** 从 content 中提取图片 URL 列表 */
    _extractImages(content) {
        if (!Array.isArray(content)) return [];
        return content.filter(b => b.type === 'image_url').map(b => b.image_url.url);
    },

    /** 格式化 token 数量 */
    _formatTokens(n) {
        if (!n) return '0';
        return n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
    },

    /** 在 AI 消息底部追加 usage 信息(灰色小字) */
    _appendUsageInfo(parentEl, inTokens, outTokens, modelName) {
        if (!inTokens && !outTokens && !modelName) return;
        const el = document.createElement('div');
        el.className = 'msg-usage';
        const parts = [];
        if (modelName) parts.push(modelName);
        if (inTokens || outTokens) {
            parts.push(`${this._formatTokens(inTokens)}→${this._formatTokens(outTokens)}`);
        }
        el.textContent = parts.join(' · ');
        parentEl.appendChild(el);
    },

    /** 追加 AI 消息(左侧头像 + 内容),返回 .msg-content 容器 */
    _appendAssistantMessage(content) {
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message assistant';

        const row = document.createElement('div');
        row.className = 'msg-row';

        const avatar = document.createElement('div');
        avatar.className = 'msg-avatar';
        avatar.textContent = '🦞';

        const msgContent = document.createElement('div');
        msgContent.className = 'msg-content';
        const body = document.createElement('div');
        body.className = 'markdown-body';
        if (content) {
            body.innerHTML = Utils.renderMarkdown(content);
            this._addCopyButtons(body);
        }
        msgContent.appendChild(body);

        row.appendChild(avatar);
        row.appendChild(msgContent);
        el.appendChild(row);
        container.appendChild(el);
        this._scrollToBottom();
        // 返回 .msg-content 使 tool/thinking 块插入到正确位置
        return msgContent;
    },

    /** 追加思考块(默认折叠)。beforeNode 存在时插入到该节点之前 */
    _appendThinkingBlock(parentEl, content, collapsed = true, beforeNode = null) {
        const block = document.createElement('div');
        block.className = 'thinking-block' + (collapsed ? '' : ' expanded');
        const header = document.createElement('div');
        header.className = 'thinking-header';
        const charCount = content ? content.length : 0;
        header.innerHTML = `💭 <span class="thinking-label">思考完成 (${charCount}字)</span>`;
        header.onclick = () => block.classList.toggle('expanded');
        const body = document.createElement('div');
        body.className = 'thinking-content';
        body.textContent = content;
        block.appendChild(header);
        block.appendChild(body);
        if (beforeNode) {
            parentEl.insertBefore(block, beforeNode);
        } else {
            parentEl.appendChild(block);
        }
        return block;
    },

    /** 追加工具调用块(默认折叠) */
    _appendToolBlock(parentEl, name, args, content, success, toolCallId) {
        const block = document.createElement('div');
        block.className = 'tool-block';
        if (toolCallId) {
            block.dataset.toolCallId = toolCallId;
            // 用 session_id + tool_call_id 作为 key 避免跨 session 冲突
            const key = this.currentSessionId ? `${this.currentSessionId}:${toolCallId}` : toolCallId;
            this.toolBlocks[key] = block;
        }

        // 头部：图标 + 工具名 + 参数预览 + 结果预览
        const header = document.createElement('div');
        const statusClass = success === false ? 'error' : success === null ? 'pending' : 'success';
        header.className = `tool-header ${statusClass}`;
        const icon = success === false ? '✗' : success === null ? '🔧' : '✓';
        const argPreview = Utils.formatArgs(args, 60);
        const resultPreview = content ? Utils.truncate(content.split('\n')[0], 60) : '';
        let headerHtml = `${icon} ${Utils.escapeHtml(name)}(${Utils.escapeHtml(argPreview)})`;
        if (resultPreview) {
            headerHtml += `<span style="color:var(--text-secondary);margin-left:8px">→ ${Utils.escapeHtml(resultPreview)}</span>`;
        }
        header.innerHTML = headerHtml;
        header.onclick = () => block.classList.toggle('expanded');
        block.appendChild(header);

        // 展开内容区
        const contentEl = document.createElement('div');
        contentEl.className = 'tool-content';

        // 工具参数
        if (args && args !== '{}') {
            const argsSection = document.createElement('div');
            argsSection.innerHTML = `<div style="color:var(--text-secondary);margin-bottom:4px;font-size:11px">参数:</div><pre style="margin:0 0 8px 0">${Utils.escapeHtml(this._formatJson(args))}</pre>`;
            contentEl.appendChild(argsSection);
        }

        // Edit 工具：显示 diff 视图
        if (name === 'Edit' && content) {
            const diffContainer = document.createElement('div');
            diffContainer.innerHTML = this._renderEditDiff(args, content);
            contentEl.appendChild(diffContainer);
        } else if (content) {
            // 普通工具输出
            const outputSection = document.createElement('div');
            outputSection.innerHTML = `<div style="color:var(--text-secondary);margin-bottom:4px;font-size:11px">输出:</div><pre style="margin:0">${Utils.escapeHtml(content)}</pre>`;
            contentEl.appendChild(outputSection);
        }

        block.appendChild(contentEl);
        parentEl.appendChild(block);
        return block;
    },

    /** 渲染 Edit 工具的 diff 视图 */
    _renderEditDiff(args, content) {
        let oldText = '', newText = '';
        try {
            const parsed = typeof args === 'string' ? JSON.parse(args) : args;
            oldText = parsed.old_string || parsed.old_text || '';
            newText = parsed.new_string || parsed.new_text || '';
        } catch (e) {
            // 解析失败,显示原始内容
            return `<pre>${Utils.escapeHtml(content)}</pre>`;
        }

        if (!oldText && !newText) {
            return `<pre>${Utils.escapeHtml(content)}</pre>`;
        }

        // 将 diff 数据存到父级 tool-block 的 dataset
        const escapedOld = Utils.escapeHtml(oldText).replace(/"/g, '&quot;');
        const escapedNew = Utils.escapeHtml(newText).replace(/"/g, '&quot;');
        let html = `<div class="diff-controls" data-diff-old="${escapedOld}" data-diff-new="${escapedNew}" style="margin-bottom:8px">`;
        html += '<button class="btn-secondary diff-btn active" data-mode="unified" onclick="Chat._switchDiffView(this, \'unified\')" style="font-size:11px;padding:2px 8px;margin-right:4px">Unified</button>';
        html += '<button class="btn-secondary diff-btn" data-mode="split" onclick="Chat._switchDiffView(this, \'split\')" style="font-size:11px;padding:2px 8px">Split</button>';
        html += '</div>';
        html += `<div class="diff-body">${Utils.renderDiff(oldText, newText, 'unified')}</div>`;
        return html;
    },

    /** 切换 diff 视图 */
    _switchDiffView(btn, mode) {
        const controls = btn.parentElement;
        controls.querySelectorAll('.diff-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const body = controls.nextElementSibling;
        // 从 controls 的 dataset 获取 old/new text 并重新渲染
        const oldText = controls.dataset.diffOld || '';
        const newText = controls.dataset.diffNew || '';
        body.innerHTML = Utils.renderDiff(oldText, newText, mode);
    },

    /** 为代码块添加复制按钮 */
    _addCopyButtons(container) {
        container.querySelectorAll('pre code').forEach(codeEl => {
            const pre = codeEl.parentElement;
            if (pre.querySelector('.copy-btn')) return;
            const btn = document.createElement('button');
            btn.className = 'copy-btn';
            btn.textContent = '复制';
            btn.onclick = (e) => {
                e.stopPropagation();
                navigator.clipboard.writeText(codeEl.textContent).then(() => {
                    btn.textContent = '已复制';
                    setTimeout(() => btn.textContent = '复制', 2000);
                });
            };
            pre.style.position = 'relative';
            pre.appendChild(btn);
        });
    },

    // ============================================================
    //  流式输出
    // ============================================================

    /** 重置流式状态 */
    _resetStreamingState() {
        this.streamingEl = null;
        this.streamingContent = '';
        this.streamingBody = null;
        this.thinkingEl = null;
        this.thinkingContent = '';
    },

    // ============================================================
    //  辅助函数
    // ============================================================

    /** 提取文本内容 */
    _extractText(content) {
        if (typeof content === 'string') return content;
        if (Array.isArray(content)) {
            return content.filter(b => b.type === 'text').map(b => b.text).join('\n');
        }
        return String(content || '');
    },

    /** 格式化 JSON */
    _formatJson(str) {
        if (typeof str !== 'string') {
            try { return JSON.stringify(str, null, 2); } catch (e) { return String(str); }
        }
        try { return JSON.stringify(JSON.parse(str), null, 2); } catch (e) { return str; }
    },

    /** 滚动到底部 */
    _scrollToBottom() {
        const container = document.getElementById('chat-messages');
        requestAnimationFrame(() => {
            container.scrollTop = container.scrollHeight;
        });
    },

    // ============================================================
    //  WS 事件处理器
    // ============================================================

    _onSessionCreated(msg) {
        this.currentSessionId = msg.session_id;
        SessionPanel.activeSessionId = msg.session_id;
        // 从消息中获取 root_dir(如果后端返回了的话)
        if (msg.root_dir) {
            SessionPanel.activeProjectDir = msg.root_dir;
        }
        // 通知后端当前活跃会话(确保权限请求能正确路由)
        WS.send({ type: 'set_active', session_id: msg.session_id });
        // 更新状态栏(新会话尚未保存到磁盘,跳过会话详情请求)
        SessionPanel._updateStatusBar(SessionPanel.activeProjectDir, msg.session_id, true);
        // 刷新会话列表(后端已创建会话)
        SessionPanel._refreshSessions();
    },

    _onUser(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        if (Array.isArray(msg.content)) {
            const text = this._extractText(msg.content);
            const images = this._extractImages(msg.content);
            // [system] 前缀的消息显示为系统消息,带图片时一并展示
            if (text.startsWith('[system]')) {
                if (images.length > 0) {
                    this._appendSystemMessageWithImages(text, images);
                } else {
                    this._appendSystemMessage(text);
                }
                return;
            }
            // 普通多模态消息：发送时已显示纯文字,此处补充图片
            if (images.length > 0) {
                const container = document.getElementById('chat-messages');
                const userMsgs = container.querySelectorAll('.message.user');
                const lastMsg = userMsgs.length > 0 ? userMsgs[userMsgs.length - 1] : null;
                if (lastMsg && !lastMsg.querySelector('.msg-image-grid')) {
                    this._appendImagesToLastUserMessage(images);
                }
            }
        }
    },

    _onThinkingStart(msg) {
        if (msg && msg.session_id && msg.session_id !== this.currentSessionId) return;
        if (this.thinkingEl) return;
        // 如果还没有流式消息容器,先创建(确保思考块在消息内部,与刷新后一致)
        if (!this.streamingEl) {
            this.streamingEl = this._appendAssistantMessage('');
            this.streamingBody = this.streamingEl.querySelector('.markdown-body');
            this.streamingContent = '';
        }
        const block = document.createElement('div');
        block.className = 'thinking-block';
        const header = document.createElement('div');
        header.className = 'thinking-header';
        header.innerHTML = '💭 <span class="thinking-label">思考中...</span>';
        header.onclick = () => block.classList.toggle('expanded');
        const body = document.createElement('div');
        body.className = 'thinking-content';
        block.appendChild(header);
        block.appendChild(body);
        // 插入到消息内容区的最前面(与刷新后 _appendThinkingBlock 的 beforeNode 逻辑一致)
        const msgContent = this.streamingEl;
        const firstChild = msgContent.firstChild;
        if (firstChild) {
            msgContent.insertBefore(block, firstChild);
        } else {
            msgContent.appendChild(block);
        }
        this.thinkingEl = block;
        this.thinkingContent = '';
        this._scrollToBottom();
    },

    _onThinking(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        if (!this.thinkingEl) return;
        this.thinkingContent += msg.content;
        const content = this.thinkingEl.querySelector('.thinking-content');
        if (content) {
            content.textContent = this.thinkingContent;
            // 更新头部显示长度
            const label = this.thinkingEl.querySelector('.thinking-label');
            if (label) {
                const len = this.thinkingContent.length;
                label.textContent = len > 0 ? `思考中... (${len}字)` : '思考中...';
            }
        }
        this._scrollToBottom();
    },

    _onText(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        // 结束思考块
        if (this.thinkingEl) {
            const label = this.thinkingEl.querySelector('.thinking-label');
            if (label) label.textContent = `思考完成 (${this.thinkingContent.length}字)`;
            this.thinkingEl = null;
            this.thinkingContent = '';
        }
        // 开始或继续流式输出(复用 _onThinkingStart 或 _onAssistant 已创建的元素)
        if (!this.streamingEl) {
            this.streamingEl = this._appendAssistantMessage('');
            this.streamingBody = this.streamingEl.querySelector('.markdown-body');
            this.streamingContent = '';
        }
        // 首次收到 text 时,streamingBody 可能还未创建(思考块占据了内容区)
        if (!this.streamingBody) {
            this.streamingBody = document.createElement('div');
            this.streamingBody.className = 'markdown-body';
            this.streamingEl.appendChild(this.streamingBody);
        }
        this.streamingContent += msg.content;
        if (this.streamingBody) {
            this.streamingBody.innerHTML = Utils.renderMarkdown(this.streamingContent);
            this._addCopyButtons(this.streamingBody);
        }
        this._scrollToBottom();
    },

    _onAssistant(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        // 关闭思考块
        if (this.thinkingEl) {
            const label = this.thinkingEl.querySelector('.thinking-label');
            if (label) label.textContent = `思考完成 (${this.thinkingContent.length}字)`;
            this.thinkingEl = null;
            this.thinkingContent = '';
        }
        // 如果没有流式元素但有内容或工具调用,先创建消息容器
        if (!this.streamingEl && (msg.content || (msg.tool_calls && msg.tool_calls.length > 0))) {
            this.streamingEl = this._appendAssistantMessage('');
            this.streamingBody = this.streamingEl.querySelector('.markdown-body');
            this.streamingContent = '';
        }
        // 确保 streamingBody 存在(思考阶段可能已创建 streamingEl 但没有 body)
        if (this.streamingEl && !this.streamingBody) {
            this.streamingBody = this.streamingEl.querySelector('.markdown-body');
            if (!this.streamingBody) {
                this.streamingBody = document.createElement('div');
                this.streamingBody.className = 'markdown-body';
                this.streamingEl.appendChild(this.streamingBody);
            }
        }
        // 用完整内容替换流式输出
        if (this.streamingBody && msg.content) {
            this.streamingBody.innerHTML = Utils.renderMarkdown(msg.content);
            this._addCopyButtons(this.streamingBody);
        }
        // 渲染工具调用
        if (msg.tool_calls && msg.tool_calls.length > 0 && this.streamingEl) {
            msg.tool_calls.forEach(tc => {
                const name = tc.function ? tc.function.name : (tc.name || 'tool');
                const args = tc.function ? tc.function.arguments : (tc.arguments || '{}');
                const tcId = tc.id || '';
                this._appendToolBlock(this.streamingEl, name, args, null, null, tcId);
            });
        }
        // 在消息内显示 usage 信息
        if (this.streamingEl) {
            this._appendUsageInfo(this.streamingEl, msg.in_tokens, msg.out_tokens, msg.model_name);
        }
        // 更新 token 统计
        if (msg.in_tokens !== undefined || msg.out_tokens !== undefined) {
            const inp = msg.in_tokens || 0;
            const out = msg.out_tokens || 0;
            const total = inp + out;
            const fmt = (n) => n >= 1000 ? `${(n / 1000).toFixed(1)}k` : `${n}`;
            const display = `Tokens: ${fmt(inp)}→${fmt(out)} (${fmt(total)})`;
            document.getElementById('status-tokens').textContent = display;
        }
        if (msg.model_name) {
            document.getElementById('status-model').textContent = msg.model_name;
        }
        // 重置流式状态
        this.streamingEl = null;
        this.streamingContent = '';
        this.streamingBody = null;
    },

    _onToolPreparing(msg) {
        // 可选：显示工具准备中的视觉提示
    },

    _onToolStart(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        // 结束思考块
        if (this.thinkingEl) {
            const label = this.thinkingEl.querySelector('.thinking-label');
            if (label) label.textContent = `思考完成 (${this.thinkingContent.length}字)`;
            this.thinkingEl = null;
            this.thinkingContent = '';
        }
        // 检查 _onAssistant 是否已创建过该工具块(避免重复创建覆盖引用)
        const key = msg.tool_call_id ? `${msg.session_id}:${msg.tool_call_id}` : null;
        const existing = key ? this.toolBlocks[key] : null;
        if (existing) {
            // 已存在：更新状态为"执行中"
            const header = existing.querySelector('.tool-header');
            if (header) {
                header.className = 'tool-header pending';
            }
        } else {
            // 不存在：新建工具块(兼容无 tool_call_id 或 _onAssistant 未覆盖的情况)
            const parent = this.streamingEl || document.getElementById('chat-messages');
            this._appendToolBlock(parent, msg.name, msg.args, '执行中...', null, msg.tool_call_id);
        }
    },

    _onToolEnd(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        // 查找对应的工具块并更新(使用 scoped key)
        const key = msg.tool_call_id ? `${msg.session_id}:${msg.tool_call_id}` : null;
        const block = key ? this.toolBlocks[key] : null;
        if (block) {
            const header = block.querySelector('.tool-header');
            const contentEl = block.querySelector('.tool-content');
            const success = !(msg.content && msg.content.startsWith('[TOOL_ERROR]'));
            const icon = success ? '✓' : '✗';
            const statusClass = success ? 'success' : 'error';
            const argPreview = Utils.formatArgs(msg.args, 60);
            const resultPreview = msg.content ? Utils.truncate(msg.content.split('\n')[0], 60) : '';

            if (header) {
                header.className = `tool-header ${statusClass}`;
                let html = `${icon} ${Utils.escapeHtml(msg.name)}(${Utils.escapeHtml(argPreview)})`;
                if (resultPreview) {
                    html += `<span style="color:var(--text-secondary);margin-left:8px">→ ${Utils.escapeHtml(resultPreview)}</span>`;
                }
                header.innerHTML = html;
            }
            if (contentEl) {
                contentEl.innerHTML = '';
                // 参数
                if (msg.args && Object.keys(msg.args).length > 0) {
                    const argsSection = document.createElement('div');
                    argsSection.innerHTML = `<div style="color:var(--text-secondary);margin-bottom:4px;font-size:11px">参数:</div><pre style="margin:0 0 8px 0">${Utils.escapeHtml(this._formatJson(msg.args))}</pre>`;
                    contentEl.appendChild(argsSection);
                }
                // Edit 工具 diff
                if (msg.name === 'Edit' && msg.content) {
                    const diffContainer = document.createElement('div');
                    diffContainer.innerHTML = this._renderEditDiff(msg.args, msg.content);
                    contentEl.appendChild(diffContainer);
                } else if (msg.content) {
                    const outputSection = document.createElement('div');
                    outputSection.innerHTML = `<div style="color:var(--text-secondary);margin-bottom:4px;font-size:11px">输出:</div><pre style="margin:0">${Utils.escapeHtml(msg.content)}</pre>`;
                    contentEl.appendChild(outputSection);
                }
            }
        }
    },

    _onConfigChanged(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        // 异步获取最新 config,更新状态栏和 todolist
        fetch(`/api/config?session_id=${msg.session_id}`)
            .then(r => r.json())
            .then(data => {
                // 更新状态栏
                if (data.model_name) {
                    document.getElementById('status-model').textContent = data.model_name;
                }
                if (data.permission_mode) {
                    const modeMap = {
                        'auto': '🔒 Auto',
                        'manual': '🔐 Manual',
                        'accept_all': '✅ Accept All',
                        'plan': '📋 Plan',
                    };
                    const display = modeMap[data.permission_mode] || `🔒 ${data.permission_mode}`;
                    document.getElementById('status-permission').textContent = display;
                }
                // 更新 todolist
                this._renderTodolist(data.todolist);
            })
            .catch(() => {});
    },

    _renderTodolist(todo) {
        const area = document.getElementById('todolist-area');
        if (!todo || !todo.items || todo.items.length === 0) {
            area.style.display = 'none';
            return;
        }
        area.style.display = 'block';
        area.innerHTML = todo.items.map(item => {
            const cls = item.status === 'completed' ? 'completed' : item.status === 'in_progress' ? 'in_progress' : '';
            const icon = item.status === 'completed' ? '[✓]' : item.status === 'in_progress' ? '[*]' : '[ ]';
            return `<div class="todolist-item ${cls}"><span>${icon}</span> ${Utils.escapeHtml(item.content)}</div>`;
        }).join('');
    },

    /** 获取 config 并渲染 todolist(用于会话切换) */
    _fetchAndRenderTodolist(sessionId) {
        fetch(`/api/config?session_id=${sessionId}`)
            .then(r => r.json())
            .then(data => this._renderTodolist(data.todolist))
            .catch(() => {
                document.getElementById('todolist-area').style.display = 'none';
            });
    },

    _onEnd(msg) {
        if (msg.session_id !== this.currentSessionId) return;
        this._resetStreamingState();
        // 刷新会话列表(session 已保存到磁盘)
        SessionPanel._refreshSessions();
    },

    _onSystemMessage(msg) {
        console.log('[Chat] system_message:', msg);
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        this._appendSystemMessage(msg.content || '');
    },

    _onError(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        this._appendSystemMessage(`❌ ${msg.message}`);
    },

    _onInterrupted(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        this._resetStreamingState();
        this._appendSystemMessage(`⏹️ ${msg.message || '已中断'}`);
    },

    _onShellResult(msg) {
        // 只显示来自聊天框 ! 命令的结果(非控制台)
        if (msg.source === 'console') return;
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        this._renderShellResult(msg.command || '', msg.output || '');
    },

    /** 从历史消息渲染 shell 命令结果(格式：[system](用户执行Shell命令)\n$ cmd\noutput) */
    _appendShellResultFromHistory(text) {
        // 去掉 [system] 前缀和 (用户执行Shell命令) 标签
        const lines = text.replace(/^\[system\]\s*\(用户执行Shell命令\)\s*\n?/, '').split('\n');
        let cmd = '';
        let output = '';
        if (lines.length > 0 && lines[0].startsWith('$ ')) {
            cmd = lines[0].substring(2);
            output = lines.slice(1).join('\n');
        } else {
            output = lines.join('\n');
        }
        this._renderShellResult(cmd, output);
    },

    /** 渲染 shell 命令结果(复用于实时和历史) */
    _renderShellResult(cmd, output) {
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message system shell-result';
        el.innerHTML = `<div style="color:var(--text-secondary);font-size:11px;margin-bottom:2px">$ ${Utils.escapeHtml(cmd)}</div><pre style="margin:0;white-space:pre-wrap">${Utils.escapeHtml(output)}</pre>`;
        container.appendChild(el);
        this._scrollToBottom();
    },

    _onCommandOutput(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message system command-output';
        const levelColors = { info: 'var(--text-secondary)', ok: '#4caf50', warn: '#ff9800', err: '#f44336' };
        const color = levelColors[msg.level] || 'var(--text-secondary)';
        el.innerHTML = `<pre style="margin:0;white-space:pre-wrap;color:${color}">${Utils.escapeHtml(msg.content || '')}</pre>`;
        container.appendChild(el);
        this._scrollToBottom();
    },

    _onCommandResult(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        if (!msg.output) return;
        const container = document.getElementById('chat-messages');
        const el = document.createElement('div');
        el.className = 'message system command-result';
        el.innerHTML = `<div style="color:var(--text-secondary);font-size:11px;margin-bottom:2px">/${Utils.escapeHtml(msg.command || '')}</div><pre style="margin:0;white-space:pre-wrap">${Utils.escapeHtml(msg.output)}</pre>`;
        container.appendChild(el);
        this._scrollToBottom();
    },

    _spinnerTimer: null,
    _spinnerChars: ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'],

    _onSpinner(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        const area = document.getElementById('spinner-area');
        let line = area.querySelector(`[data-wid="${msg.wait_id}"]`);
        if (!line) {
            line = document.createElement('div');
            line.className = 'spinner-line';
            line.dataset.wid = msg.wait_id;
            line.dataset.frame = '0';
            line.dataset.text = msg.text;
            line.dataset.startTime = Date.now().toString();
            area.appendChild(line);
        }
        line.dataset.text = msg.text;
        this._ensureSpinnerTimer();
    },

    _onSpinnerStop(msg) {
        if (msg.session_id && msg.session_id !== this.currentSessionId) return;
        const area = document.getElementById('spinner-area');
        const line = area.querySelector(`[data-wid="${msg.wait_id}"]`);
        if (line) line.remove();
        if (!area.children.length) this._stopSpinnerTimer();
    },

    /** 启动 spinner 动画定时器(学 TUI 的 _spinner_task,100ms 一帧) */
    _ensureSpinnerTimer() {
        if (this._spinnerTimer) return;
        this._spinnerTimer = setInterval(() => {
            const area = document.getElementById('spinner-area');
            if (!area || !area.children.length) { this._stopSpinnerTimer(); return; }
            for (const line of area.children) {
                let frame = parseInt(line.dataset.frame || '0');
                const char = this._spinnerChars[frame % this._spinnerChars.length];
                line.dataset.frame = ((frame + 1) % this._spinnerChars.length).toString();
                const elapsed = this._formatDuration(Date.now() - parseInt(line.dataset.startTime || '0'));
                line.textContent = `${char} ${line.dataset.text || ''} [${elapsed}]`;
            }
        }, 100);
    },

    /** 格式化持续时间(学 TUI 的 _format_duration) */
    _formatDuration(ms) {
        const seconds = ms / 1000;
        if (seconds < 1) return `${ms}ms`;
        if (seconds < 60) return `${seconds.toFixed(1)}s`;
        if (seconds < 3600) {
            const minutes = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${minutes}m${secs}s`;
        }
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        return `${hours}h${minutes}m`;
    },

    _stopSpinnerTimer() {
        if (this._spinnerTimer) { clearInterval(this._spinnerTimer); this._spinnerTimer = null; }
    },
};
