/* utils.js — 工具函数 */

const Utils = {
    /** Markdown 渲染 */
    renderMarkdown(text) {
        if (!text) return '';
        // 配置 marked
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                highlight: function(code, lang) {
                    if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                        return hljs.highlight(code, { language: lang }).value;
                    }
                    return code;
                },
                breaks: true,
            });
            return marked.parse(text);
        }
        return this.escapeHtml(text).replace(/\n/g, '<br>');
    },

    /** HTML 转义 */
    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    },

    /** 格式化工具参数 */
    formatArgs(args, maxLen = 80) {
        if (!args) return '';
        const str = typeof args === 'string' ? args : JSON.stringify(args);
        if (str.length <= maxLen) return str;
        return str.substring(0, maxLen) + '...';
    },

    /** 格式化时间 */
    formatTime(ts) {
        if (!ts) return '';
        // 后端格式 "2024-01-15 10:30:00" 或 ISO 格式,统一转 ISO 再解析
        const d = new Date(ts.replace(' ', 'T'));
        if (isNaN(d.getTime())) return ts; // 解析失败直接返回原字符串
        const pad = n => String(n).padStart(2, '0');
        return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
    },

    /** 格式化 token 统计 */
    formatTokens(usage) {
        if (!usage) return 'Tokens: -';
        const inp = usage.input_tokens || usage.in_tokens || 0;
        const out = usage.output_tokens || usage.out_tokens || 0;
        const total = inp + out;
        if (total >= 1000) {
            return `Tokens: ${(total / 1000).toFixed(1)}k`;
        }
        return `Tokens: ${total}`;
    },

    /** 截断文本 */
    truncate(text, maxLen = 100) {
        if (!text || text.length <= maxLen) return text || '';
        return text.substring(0, maxLen) + '...';
    },

    /** 防抖 */
    debounce(fn, ms) {
        let timer;
        return function(...args) {
            clearTimeout(timer);
            timer = setTimeout(() => fn.apply(this, args), ms);
        };
    },

    /** 显示 toast */
    showToast(message, duration = 2000) {
        const toast = document.createElement('div');
        toast.className = 'toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), duration);
    },

    /** 渲染 Diff 视图 */
    renderDiff(oldText, newText, mode = 'unified') {
        if (mode === 'split') {
            return this._renderSplitDiff(oldText, newText);
        }
        return this._renderUnifiedDiff(oldText, newText);
    },

    _renderUnifiedDiff(oldText, newText) {
        const oldLines = (oldText || '').split('\n');
        const newLines = (newText || '').split('\n');
        let html = '<div class="diff-view">';
        const maxLen = Math.max(oldLines.length, newLines.length);
        for (let i = 0; i < maxLen; i++) {
            const old = oldLines[i];
            const newL = newLines[i];
            if (old === newL) {
                html += `<div class="diff-line context">${this.escapeHtml(old || '')}</div>`;
            } else {
                if (old !== undefined) html += `<div class="diff-line remove">- ${this.escapeHtml(old)}</div>`;
                if (newL !== undefined) html += `<div class="diff-line add">+ ${this.escapeHtml(newL)}</div>`;
            }
        }
        html += '</div>';
        return html;
    },

    _renderSplitDiff(oldText, newText) {
        const oldLines = (oldText || '').split('\n');
        const newLines = (newText || '').split('\n');
        let html = '<div class="diff-view" style="display:flex;gap:8px">';
        html += '<div style="flex:1">';
        oldLines.forEach(l => {
            html += `<div class="diff-line remove">${this.escapeHtml(l)}</div>`;
        });
        html += '</div><div style="flex:1">';
        newLines.forEach(l => {
            html += `<div class="diff-line add">${this.escapeHtml(l)}</div>`;
        });
        html += '</div></div>';
        return html;
    },

    /** 显示加载状态 */
    showLoading(text = '加载中...') {
        const overlay = document.getElementById('loading-overlay');
        const loadingText = document.getElementById('loading-text');
        if (overlay && loadingText) {
            loadingText.textContent = text;
            overlay.classList.add('active');
        }
    },

    /** 隐藏加载状态 */
    hideLoading() {
        const overlay = document.getElementById('loading-overlay');
        if (overlay) {
            overlay.classList.remove('active');
        }
    },

    /** 显示错误提示 */
    showError(message, duration = 3000) {
        const toast = document.createElement('div');
        toast.className = 'error-toast';
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), duration);
    },

    /** 带加载状态的 fetch 请求 */
    async fetchWithLoading(url, options = {}, loadingText = '加载中...') {
        this.showLoading(loadingText);
        try {
            const response = await fetch(url, options);
            if (!response.ok) {
                const error = await response.json().catch(() => ({ detail: response.statusText }));
                throw new Error(error.detail || `请求失败: ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            this.showError(error.message);
            throw error;
        } finally {
            this.hideLoading();
        }
    },

    /** 确认对话框 */
    confirm(message) {
        return new Promise((resolve) => {
            const modal = document.createElement('div');
            modal.className = 'modal';
            modal.style.display = 'flex';
            modal.innerHTML = `
                <div class="modal-content" style="max-width:360px">
                    <h3>确认操作</h3>
                    <div class="modal-body">
                        <p style="font-size:13px;color:var(--text-primary)">${this.escapeHtml(message)}</p>
                    </div>
                    <div class="modal-actions">
                        <button class="btn-secondary" id="confirm-cancel">取消</button>
                        <button class="btn-primary" id="confirm-ok">确认</button>
                    </div>
                </div>`;
            document.body.appendChild(modal);

            document.getElementById('confirm-cancel').onclick = () => {
                modal.remove();
                resolve(false);
            };
            document.getElementById('confirm-ok').onclick = () => {
                modal.remove();
                resolve(true);
            };
            modal.onclick = (e) => {
                if (e.target === modal) {
                    modal.remove();
                    resolve(false);
                }
            };
        });
    },

    /** 隐藏快捷键提示 */
    hideShortcutHint() {
        const hint = document.getElementById('shortcut-hint');
        if (hint) {
            hint.style.display = 'none';
        }
    },
};
