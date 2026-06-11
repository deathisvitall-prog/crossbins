// ── Sidebar toggle (viewer & editor) ─────────────────────────────────────────

const toggleSidebar = () => {
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.toggle('open');
};

// ── Copy URL to clipboard ─────────────────────────────────────────────────────

const copyURL = () => {
    const url = location.href;
    if (navigator.clipboard) {
        navigator.clipboard.writeText(url).then(() => showToast('Copied URL to clipboard!'));
    } else {
        const el = document.createElement('textarea');
        el.value = url;
        el.style.position = 'fixed';
        el.style.opacity = '0';
        document.body.appendChild(el);
        el.select();
        document.execCommand('copy');
        document.body.removeChild(el);
        showToast('Copied URL to clipboard!');
    }
};

// ── Toast notification (lightweight, no library needed) ───────────────────────

const showToast = (msg, duration = 3000) => {
    let container = document.getElementById('db-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.id = 'db-toast-container';
        container.style.cssText = [
            'position:fixed', 'bottom:20px', 'right:20px', 'z-index:9999',
            'display:flex', 'flex-direction:column', 'gap:8px', 'pointer-events:none'
        ].join(';');
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.style.cssText = [
        'background:#1a1a1a', 'border:1px solid #2a2a2a', 'color:#ccc',
        'padding:8px 14px', 'border-radius:2px', 'font-size:12px',
        'font-family:\'Courier New\',monospace', 'opacity:0',
        'transition:opacity 0.2s ease'
    ].join(';');
    toast.textContent = msg;
    container.appendChild(toast);
    requestAnimationFrame(() => { toast.style.opacity = '1'; });
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 200);
    }, duration);
};

// ── Keyboard shortcuts ────────────────────────────────────────────────────────

const _bindKeys = () => {
    const on = (key, fn) => {
        document.addEventListener('keydown', e => {
            const tag = document.activeElement.tagName;
            if (tag === 'INPUT' || tag === 'TEXTAREA') return;
            const mod = e.ctrlKey || e.metaKey;
            const k   = e.key.toLowerCase();

            if (key === 'mod+s' && mod && k === 's') { e.preventDefault(); fn(); return; }
            if (key === 'mod+c' && mod && k === 'c') { fn(); return; }
            if (!mod && k === key) { e.preventDefault(); fn(); }
        });
    };

    // Viewer shortcuts
    on('n', () => { const a = document.querySelector('.db-btn[href*="/new"]'); if (a) a.click(); });
    on('r', () => { const a = document.getElementById('btn-raw'); if (a) a.click(); });
    on('mod+c', () => {
        if (window.getSelection().toString() === '') copyURL();
    });

    // Editor shortcut
    on('mod+s', () => {
        const form = document.getElementById('paste-form');
        if (form) submitPaste();
    });
};

// ── New paste submission ──────────────────────────────────────────────────────

const submitPaste = () => {
    const titleInput   = document.getElementById('paste-title-input');
    const titleHidden  = document.getElementById('paste-title-hidden');
    const form         = document.getElementById('paste-form');

    if (!form) return;

    const title = titleInput ? titleInput.value.trim() : '';
    if (!title) {
        titleInput && titleInput.focus();
        showToast('Please enter a title.');
        return;
    }
    if (titleHidden) titleHidden.value = title;
    form.submit();
};

const clearEditor = () => {
    const ta = document.getElementById('paste-content');
    if (ta) ta.value = '';
    const ti = document.getElementById('paste-title-input');
    if (ti) ti.value = '';
};

// ── Pretty-print line highlighting ───────────────────────────────────────────

const _prettyPrintLines = () => {
    const $list = document.querySelector('ol.linenums');
    if (!$list) return;

    let _lines = _expandLines(window.location.hash);
    let $lastLine = null;

    const $lines = () => Array.from($list.querySelectorAll('li'));

    const highlight = () => {
        $lines().forEach((li, i) => {
            li.classList.toggle('selected', _lines.includes(i + 1));
        });
    };

    const manage = els => {
        els.forEach(li => {
            const n = Array.from($list.querySelectorAll('li')).indexOf(li) + 1;
            const idx = _lines.indexOf(n);
            idx < 0 ? _lines.push(n) : _lines.splice(idx, 1);
        });
        window.location.hash = _collapser();
    };

    $list.addEventListener('click', e => {
        const li = e.target.closest('li');
        if (!li) return;

        if ($lastLine && e.shiftKey) {
            const all = $lines();
            const a = all.indexOf(li), b = all.indexOf($lastLine);
            const range = all.slice(Math.min(a, b), Math.max(a, b) + 1);
            range.forEach(el => el.classList.toggle('selected'));
            manage(range);
        } else {
            li.classList.toggle('selected');
            manage([li]);
        }
        $lastLine = li;
    });

    document.addEventListener('mousedown', e => { if (e.shiftKey) e.preventDefault(); });
    highlight();
};

const _expandLines = raw => {
    if (!raw) return [];
    return raw.replace(/#/g, '').split(',').flatMap(item =>
        item.includes('-') ? _generateRange(item.split('-')) : [parseInt(item, 10)]
    ).filter((v, i, a) => !isNaN(v) && a.indexOf(v) === i).sort((a, b) => a - b);
};

const _generateRange = ([start, end]) => {
    const r = [];
    for (let i = parseInt(start, 10); i <= parseInt(end, 10); i++) r.push(i);
    return r;
};

const _collapser = () => {
    if (!_lines || !_lines.length) return '';
    const sorted = [..._lines].sort((a, b) => a - b);
    const ranges = [];
    let i = 0;
    while (i < sorted.length) {
        let rs = sorted[i], re = rs;
        while (sorted[i + 1] - sorted[i] === 1) { re = sorted[++i]; }
        ranges.push(rs === re ? `${rs}` : `${rs}-${re}`);
        i++;
    }
    return '#' + ranges.join(',');
};

// ── Paste / Comments (for future comment support) ─────────────────────────────

let reply = 0;

const openReply = id => {
    if (reply !== 0) {
        document.getElementById(`reply${reply}div`)?.remove();
        document.getElementById(`replybtn${reply}`)?.style && (document.getElementById(`replybtn${reply}`).style.display = '');
    }
    const replyBtn = document.getElementById(`replybtn${id}`);
    if (replyBtn) replyBtn.style.display = 'none';
    const container = document.querySelector(`#${id} .create-reply-container`);
    if (container) {
        container.insertAdjacentHTML('beforeend',
            `<b style="color:#d3d3d3;">Reply to Comment</b>` +
            `<textarea class="reply" id="reply-content" style="margin-top:2px;width:100%;max-width:100%;" placeholder="Your reply"></textarea>` +
            `<a href="#" class="db-btn" id="create-reply" style="cursor:pointer;margin:5px 0 10px 0;">Submit Reply</a>`
        );
    }
    reply = id;
};

const htmlspecialchars = str =>
    String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');

const age = time => {
    const diff = Math.floor(Date.now()) - time;
    if (diff > 31557600000) return `${Math.floor(diff / 31557600000)} year${Math.floor(diff / 31557600000) > 1 ? 's' : ''} ago`;
    if (diff > 2592000000)  return `${Math.floor(diff / 2592000000)} month${Math.floor(diff / 2592000000) > 1 ? 's' : ''} ago`;
    if (diff > 604800000)   return `${Math.floor(diff / 604800000)} week${Math.floor(diff / 604800000) > 1 ? 's' : ''} ago`;
    if (diff > 86400000)    return `${Math.floor(diff / 86400000)} day${Math.floor(diff / 86400000) > 1 ? 's' : ''} ago`;
    if (diff > 3600000)     return `${Math.floor(diff / 3600000)} hour${Math.floor(diff / 3600000) > 1 ? 's' : ''} ago`;
    if (diff > 60000)       return `${Math.floor(diff / 60000)} minute${Math.floor(diff / 60000) > 1 ? 's' : ''} ago`;
    if (diff > 1000)        return `${Math.floor(diff / 1000)} second${Math.floor(diff / 1000) > 1 ? 's' : ''} ago`;
    return 'now';
};

const convTime = time => {
    const match = time.toString().match(/^([01]\d|2[0-3])(:)([0-5]\d)(:[0-5]\d)?$/) || [time];
    if (match.length > 1) {
        const parts = match.slice(1);
        parts[5] = +parts[0] < 12 ? 'AM' : 'PM';
        parts[0] = +parts[0] % 12 || 12;
        return parts.join('');
    }
    return match[0];
};

const convertDate = iso => {
    const months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    const year  = iso.substr(0, 4);
    const month = months[parseInt(iso.substr(5, 2), 10) - 1] ?? '-';
    let day     = iso.substr(8, 2);
    const time  = convTime(iso.substr(11, 5));
    if (day.charAt(0) === '0') day = day.substr(1);
    const suffix = { '1': 'st', '2': 'nd', '3': 'rd' }[day.slice(-1)] ?? 'th';
    return `${month} ${day}${suffix}, ${year} - ${time}`;
};

// ── Auth / Logout ─────────────────────────────────────────────────────────────

const _bindLogout = () => {
    document.querySelectorAll('.logout-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.preventDefault();
            const token = document.querySelector('input[name=_token]')?.value ?? '';
            fetch('/logout', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `_token=${encodeURIComponent(token)}`
            })
            .then(r => r.json())
            .then(resp => resp.status === 'done' ? location.reload() : alert(resp.msg))
            .catch(() => alert('Logout failed.'));
        });
    });
};

// ── Init ──────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    _bindKeys();
    _bindLogout();
    _prettyPrintLines();
});
