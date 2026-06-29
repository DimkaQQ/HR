'use strict';

// ── Config (injected from template) ──────────────────────────────────────────
let ME_ID, WS_TOKEN;

// ── State ─────────────────────────────────────────────────────────────────────
let ws = null;
let wsReconnectAttempts = 0;
let wsReconnectTimer = null;

let currentConvId = null;
let currentConvInfo = null;
let conversations = [];               // ordered list
let convMap = new Map();              // id -> conv object

let replyTo = null;                   // {id, sender_name, text}
let typingTimeouts = new Map();       // `${convId}_${userId}` -> timerID
let typingUsers = new Map();          // convId -> Set<userId>
let lastTypingSentAt = 0;
let typingStopTimer = null;

let oldestMsgId = null;
let hasMoreMessages = true;
let isLoadingMore = false;
let isAtBottom = true;

// ── DOM refs (set in init) ────────────────────────────────────────────────────
let $messages, $input, $sendBtn, $replyBar, $replyName, $replyText, $scrollBtn,
    $convList, $chatArea, $chatWelcome, $chatHeader, $typingEl, $connStatus,
    $loadMoreBtn, $emojiPicker, $searchInput;

// ── Constants ─────────────────────────────────────────────────────────────────
const EMOJIS = [
  '😀','😃','😄','😁','😅','😂','🤣','😊','😇','🙂','🙃','😉','😌','😍','🥰','😘','😋',
  '😛','😝','😜','🤪','😎','🤩','🥳','😏','😒','😔','😟','😕','🙁','😣','😖','😫','😩',
  '🥺','😢','😭','😤','😠','🤬','🤯','😳','🥵','🥶','😱','😨','😰','😥','😓','🤗','🤔',
  '🤭','🤫','🤥','😶','😐','😑','😬','🙄','😯','😲','🥱','😴','🤤','😪','😵','🤒','🤑',
  '😈','👿','💀','🤡','👻','😺','😸','🙀','😿','👋','✋','👌','✌️','🤞','👍','👎','✊',
  '👏','🙌','🙏','💪','❤️','🧡','💛','💚','💙','💜','🖤','💔','💕','💞','💓','💗','💖',
  '💝','🔥','✅','❌','⭐','🎉','🎊','🥂','🎂','🎁','🌟','💯','🚀','😷','🤧','🥴','🤢',
];

const MONTHS_RU = ['января','февраля','марта','апреля','мая','июня','июля','августа','сентября','октября','ноября','декабря'];
const DAYS_RU = ['вс','пн','вт','ср','чт','пт','сб'];

// ── Init ──────────────────────────────────────────────────────────────────────
function chatInit(meId, wsToken) {
  ME_ID = meId;
  WS_TOKEN = wsToken;

  $messages    = document.getElementById('messages');
  $input       = document.getElementById('msg-input');
  $sendBtn     = document.getElementById('send-btn');
  $replyBar    = document.getElementById('reply-bar');
  $replyName   = document.getElementById('reply-name');
  $replyText   = document.getElementById('reply-text');
  $scrollBtn   = document.getElementById('scroll-btn');
  $convList    = document.getElementById('conv-list');
  $chatArea    = document.getElementById('chat-area');
  $chatWelcome = document.getElementById('chat-welcome');
  $chatHeader  = document.getElementById('chat-header-info');
  $typingEl    = document.getElementById('typing-indicator');
  $connStatus  = document.getElementById('conn-status');
  $loadMoreBtn = document.getElementById('load-more-btn');
  $emojiPicker = document.getElementById('emoji-picker');
  $searchInput = document.getElementById('search-input');

  buildEmojiPicker();
  bindEvents();
  connectWS();
  loadConversations();
  setupViewportHandler();
}

// ── WebSocket ──────────────────────────────────────────────────────────────────
function connectWS() {
  if (ws && ws.readyState === WebSocket.OPEN) return;
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  ws = new WebSocket(`${proto}://${location.host}/chat/ws?token=${WS_TOKEN}`);

  ws.onopen = () => {
    wsReconnectAttempts = 0;
    if (wsReconnectTimer) { clearTimeout(wsReconnectTimer); wsReconnectTimer = null; }
    $connStatus && $connStatus.classList.add('hidden');
  };

  ws.onmessage = e => { try { dispatch(JSON.parse(e.data)); } catch(_) {} };

  ws.onclose = ws.onerror = () => {
    ws = null;
    $connStatus && $connStatus.classList.remove('hidden');
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (wsReconnectTimer) return;
  const delay = Math.min(1000 * Math.pow(2, wsReconnectAttempts), 30000);
  wsReconnectAttempts = Math.min(wsReconnectAttempts + 1, 6);
  wsReconnectTimer = setTimeout(() => { wsReconnectTimer = null; connectWS(); }, delay);
}

function wsSend(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(data));
  }
}

// ── Event dispatcher ──────────────────────────────────────────────────────────
function dispatch(data) {
  switch (data.type) {
    case 'message':     onIncomingMessage(data);          break;
    case 'typing':      onTyping(data);                   break;
    case 'stop_typing': onStopTyping(data);               break;
    case 'read':        onRead(data);                     break;
    case 'online':      onOnlineStatus(data);             break;
    case 'delete':      onDelete(data);                   break;
  }
}

// ── Conversations ─────────────────────────────────────────────────────────────
async function loadConversations() {
  const res = await fetch('/chat/conversations');
  conversations = await res.json();
  convMap.clear();
  conversations.forEach(c => {
    const key = c.id ?? `dm_${c.partner_id}`;
    convMap.set(key, c);
  });
  renderConvList();
}

function renderConvList() {
  $convList.innerHTML = '';
  const q = ($searchInput?.value || '').toLowerCase();
  conversations
    .filter(c => !q || c.name.toLowerCase().includes(q))
    .forEach(c => $convList.appendChild(makeConvItem(c)));
}

function roleBadge(role) {
  if (!role) return '';
  const label = role === 'manager' ? 'Менеджер' : 'Сотрудник';
  return `<span class="role-badge role-${role}">${label}</span>`;
}

function makeConvItem(c) {
  const div = document.createElement('div');
  div.className = 'conv-item';
  div.dataset.key = c.id ?? `dm_${c.partner_id}`;

  const onlineDot = c.type === 'direct'
    ? `<span class="online-dot ${c.online ? 'is-online' : ''}"></span>` : '';

  const avatarBg = c.color;
  const initials = c.initials;
  const previewHtml = _convPreviewHtml(c);
  const timeHtml = c.last_message ? `<span class="conv-time">${fmtConvTime(c.last_message.created_at)}</span>` : '';
  const badge = c.unread_count > 0 ? `<span class="conv-badge">${c.unread_count > 99 ? '99+' : c.unread_count}</span>` : '';
  const roleHtml = c.type === 'direct' && c.partner_role ? roleBadge(c.partner_role) : '';

  div.innerHTML = `
    <div class="conv-avatar-wrap">
      <div class="avatar" style="background:${avatarBg};${c.type==='general'?'font-size:18px;font-weight:700':''}">${initials}</div>
      ${onlineDot}
    </div>
    <div class="conv-body">
      <div class="conv-top">
        <span class="conv-name">${esc(c.name)}</span>${roleHtml}
        ${timeHtml}
      </div>
      <div class="conv-bottom">
        <span class="conv-preview" id="conv-preview-${c.id ?? 'dm' + c.partner_id}">${previewHtml}</span>
        ${badge}
      </div>
    </div>
  `;

  div.addEventListener('click', () => openConv(c));
  return div;
}

function _convPreviewHtml(c) {
  const typing = typingUsers.get(c.id);
  if (typing && typing.size > 0) {
    const names = [...typing.values()].slice(0, 2).join(', ');
    return `<em class="typing-preview">${esc(names)} печатает...</em>`;
  }
  if (!c.last_message) return '<span style="color:var(--muted)">Нет сообщений</span>';
  const lm = c.last_message;
  const prefix = lm.is_mine ? '<span class="preview-check">✓</span> Вы: ' : '';
  const text = lm.text.replace(/\n/g, ' ');
  return prefix + esc(text.length > 40 ? text.slice(0, 40) + '…' : text);
}

async function openConv(c) {
  // Create DM on demand
  if (!c.id && c.partner_id) {
    const r = await fetch(`/chat/direct/${c.partner_id}`);
    const d = await r.json();
    c.id = d.conv_id;
    convMap.set(c.id, c);
  }

  currentConvId = c.id;
  currentConvInfo = c;
  oldestMsgId = null;
  hasMoreMessages = true;

  // Highlight
  document.querySelectorAll('.conv-item').forEach(el => el.classList.remove('active'));
  const key = c.id ?? `dm_${c.partner_id}`;
  document.querySelector(`[data-key="${key}"]`)?.classList.add('active');

  // Header
  renderChatHeader(c);

  // Show area
  $chatWelcome.classList.add('hidden');
  $chatArea.classList.remove('hidden');

  // Reset reply and close any open overlays
  cancelReply();
  closeEmojiPicker();

  // Messages
  $messages.innerHTML = '';
  await loadMessages(c.id);
  scrollBottom(false);

  // Mark read
  wsSend({ type: 'read', conv_id: c.id });

  // Clear badge
  clearConvBadge(c.id);
  c.unread_count = 0;

  // Mobile: show chat panel, hide list panel
  document.querySelector('.wa-layout')?.classList.add('conv-open');

  // Don't auto-focus on mobile — triggers iOS keyboard immediately
  if (window.innerWidth > 768) $input.focus();
}

function mobileBackToList() {
  document.querySelector('.wa-layout')?.classList.remove('conv-open');
}

function renderChatHeader(c) {
  const isOnline = c.type === 'direct' && c.online;
  const statusText = c.type === 'general'
    ? 'Все сотрудники'
    : (isOnline ? '<span style="color:var(--success)">В сети</span>' : fmtLastSeen(c.last_seen));

  const onlineDot = c.type === 'direct'
    ? `<span class="online-dot ${isOnline ? 'is-online' : ''}" style="width:10px;height:10px;top:auto;right:auto;position:static;margin-right:2px"></span>` : '';

  const headerRoleHtml = c.type === 'direct' && c.partner_role ? roleBadge(c.partner_role) : '';

  $chatHeader.innerHTML = `
    <div class="avatar" style="background:${c.color};${c.type==='general'?'font-size:18px;font-weight:700':''};margin-right:12px">${c.initials}</div>
    <div>
      <div style="font-weight:600;font-size:15px;display:flex;align-items:center;gap:8px">${esc(c.name)}${headerRoleHtml}</div>
      <div style="font-size:12px;display:flex;align-items:center;gap:4px">${onlineDot}${statusText}</div>
    </div>
  `;
}

// ── Messages ──────────────────────────────────────────────────────────────────
async function loadMessages(convId, prepend = false) {
  if (isLoadingMore) return;
  isLoadingMore = true;
  $loadMoreBtn && ($loadMoreBtn.disabled = true);

  const url = `/chat/messages/${convId}` + (oldestMsgId ? `?before_id=${oldestMsgId}` : '');
  const r = await fetch(url);
  const msgs = await r.json();

  isLoadingMore = false;

  if (msgs.length < 40) {
    hasMoreMessages = false;
    $loadMoreBtn && $loadMoreBtn.classList.add('hidden');
  } else {
    $loadMoreBtn && $loadMoreBtn.classList.remove('hidden');
    $loadMoreBtn && ($loadMoreBtn.disabled = false);
  }

  if (msgs.length === 0) return;
  oldestMsgId = msgs[0].id;

  if (prepend) {
    const prevH = $messages.scrollHeight;
    renderMessagesBatch(msgs, true);
    $messages.scrollTop = $messages.scrollHeight - prevH;
  } else {
    renderMessagesBatch(msgs, false);
  }
}

function renderMessagesBatch(msgs, prepend = false) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < msgs.length; i++) {
    const prev = i > 0 ? msgs[i - 1] : null;
    const next = i < msgs.length - 1 ? msgs[i + 1] : null;
    const el = buildMsgEl(msgs[i], prev, next);
    if (el) frag.appendChild(el);
  }

  if (prepend && $messages.firstChild) {
    $messages.insertBefore(frag, $messages.firstChild);
  } else {
    $messages.appendChild(frag);
  }
}

function appendSingleMessage(msg) {
  // Find the last actual message row (skip date separators)
  const lastMsgEl = [...$messages.querySelectorAll('.msg-row')].at(-1);
  const prevMsg = lastMsgEl
    ? { sender_id: parseInt(lastMsgEl.dataset.senderId), created_at: lastMsgEl.dataset.createdAt }
    : null;

  // buildMsgEl handles date separators internally — don't add one here
  const el = buildMsgEl(msg, prevMsg, null);
  if (el) {
    $messages.appendChild(el);
    if (isAtBottom) {
      scrollBottom(true);
    } else {
      updateScrollBtn();
    }
  }
}

function buildMsgEl(msg, prevMsg, nextMsg) {
  const isMine = msg.is_mine;
  const senderId = msg.sender_id;
  const createdAt = new Date(msg.created_at);

  // Date separator
  const parts = [];

  if (!prevMsg) {
    parts.push(makeDateSeparator(msg.created_at));
  } else {
    const pd = new Date(prevMsg.created_at).toDateString();
    if (pd !== createdAt.toDateString()) {
      parts.push(makeDateSeparator(msg.created_at));
    }
  }

  // Grouping logic
  const prevSame = prevMsg && prevMsg.sender_id === senderId
    && (createdAt - new Date(prevMsg.created_at)) < 5 * 60 * 1000;
  const nextSame = nextMsg && nextMsg.sender_id === senderId
    && (new Date(nextMsg.created_at) - createdAt) < 5 * 60 * 1000;

  const isFirst = !prevSame;
  const isLast = !nextSame;

  const wrapper = document.createElement('div');
  wrapper.className = `msg-row ${isMine ? 'mine' : 'theirs'}`;
  wrapper.dataset.msgId = msg.id;
  wrapper.dataset.senderId = msg.sender_id;
  wrapper.dataset.createdAt = msg.created_at;
  wrapper.dataset.text = msg.is_deleted ? '' : msg.text;

  // Avatar (left side, only for first in group)
  const avatarHtml = !isMine && isFirst
    ? `<div class="avatar msg-avatar" style="background:${msg.sender_color}">${msg.sender_initials}</div>`
    : `<div class="msg-avatar-spacer"></div>`;

  // Sender name (first in group, or first in any DM to show role)
  let nameHtml = '';
  if (!isMine && isFirst) {
    const showName = currentConvInfo?.type === 'general';
    const showRole = msg.sender_role && (currentConvInfo?.type === 'general' || currentConvInfo?.type === 'direct');
    if (showName || showRole) {
      nameHtml = `<div class="msg-sender-name">
        ${showName ? `<span style="color:${msg.sender_color}">${esc(msg.sender_name)}</span>` : ''}
        ${showRole ? roleBadge(msg.sender_role) : ''}
      </div>`;
    }
  }

  // Reply preview
  let replyHtml = '';
  if (msg.reply_to) {
    replyHtml = `
      <div class="msg-reply-preview" data-reply-id="${msg.reply_to.id}">
        <div class="msg-reply-sender">${esc(msg.reply_to.sender_name)}</div>
        <div class="msg-reply-text">${esc(msg.reply_to.text)}</div>
      </div>`;
  }

  // Message text
  const textHtml = msg.is_deleted
    ? `<span class="msg-deleted">Сообщение удалено</span>`
    : linkify(esc(msg.text));

  // Read receipt (only for my messages)
  let readHtml = '';
  if (isMine && isLast) {
    readHtml = `<span class="msg-status" id="status-${msg.id}">${msg.read_by_others ? '✓✓' : '✓'}</span>`;
  }

  // Bubble corners
  let corner = 'mid';
  if (isFirst && isLast) corner = 'only';
  else if (isFirst) corner = 'first';
  else if (isLast) corner = 'last';

  wrapper.innerHTML = `
    ${!isMine ? avatarHtml : ''}
    <div class="msg-content">
      ${nameHtml}
      <div class="msg-bubble ${isMine ? 'mine' : 'theirs'} corner-${corner}" id="bubble-${msg.id}">
        ${replyHtml}
        <div class="msg-text">${textHtml}</div>
        <div class="msg-meta">
          <span class="msg-time">${fmtTime(msg.created_at)}</span>
          ${readHtml}
        </div>
      </div>
    </div>
    ${isMine ? '<div class="msg-avatar-spacer"></div>' : ''}
  `;

  // Context menu
  wrapper.querySelector('.msg-bubble').addEventListener('contextmenu', e => {
    e.preventDefault();
    showContextMenu(e, msg);
  });

  // Long press for mobile
  let pressTimer;
  wrapper.querySelector('.msg-bubble').addEventListener('touchstart', e => {
    pressTimer = setTimeout(() => showContextMenu(e.touches[0], msg), 600);
  });
  wrapper.querySelector('.msg-bubble').addEventListener('touchend', () => clearTimeout(pressTimer));

  // Click reply preview → scroll to original
  const rp = wrapper.querySelector('.msg-reply-preview');
  if (rp) {
    rp.addEventListener('click', () => scrollToMsg(rp.dataset.replyId));
  }

  const frag = document.createDocumentFragment();
  parts.forEach(p => frag.appendChild(p));
  frag.appendChild(wrapper);
  return frag;
}

function makeDateSeparator(isoStr) {
  const el = document.createElement('div');
  el.className = 'date-sep';
  el.textContent = fmtDateSep(isoStr);
  return el;
}

function scrollToMsg(msgId) {
  const el = document.querySelector(`[data-msg-id="${msgId}"]`);
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' });
    el.classList.add('highlight');
    setTimeout(() => el.classList.remove('highlight'), 1500);
  }
}

// ── Scroll ─────────────────────────────────────────────────────────────────────
function scrollBottom(smooth = true) {
  if (smooth) {
    $messages.scrollTo({ top: $messages.scrollHeight, behavior: 'smooth' });
  } else {
    $messages.scrollTop = $messages.scrollHeight;
  }
}

function updateScrollBtn() {
  const delta = $messages.scrollHeight - $messages.scrollTop - $messages.clientHeight;
  isAtBottom = delta < 60;
  if ($scrollBtn) {
    $scrollBtn.style.display = isAtBottom ? 'none' : 'flex';
  }
}

// ── Send message ───────────────────────────────────────────────────────────────
function sendMessage() {
  const text = $input.value.trim();
  if (!text || !currentConvId) return;

  wsSend({
    type: 'message',
    conv_id: currentConvId,
    text,
    reply_to_id: replyTo ? replyTo.id : null,
  });

  $input.value = '';
  $input.style.height = 'auto';
  cancelReply();
  stopTypingSignal();
}

// ── Typing ────────────────────────────────────────────────────────────────────
function onTypingInput() {
  autoResizeInput();
  if (!currentConvId) return;
  const now = Date.now();
  if (now - lastTypingSentAt > 2000) {
    wsSend({ type: 'typing', conv_id: currentConvId });
    lastTypingSentAt = now;
  }
  if (typingStopTimer) clearTimeout(typingStopTimer);
  typingStopTimer = setTimeout(stopTypingSignal, 3000);
}

function stopTypingSignal() {
  if (currentConvId) wsSend({ type: 'stop_typing', conv_id: currentConvId });
  lastTypingSentAt = 0;
}

// ── Reply ──────────────────────────────────────────────────────────────────────
function setReply(msg) {
  replyTo = { id: msg.id, sender_name: msg.sender_name, text: msg.text };
  $replyName.textContent = msg.sender_name;
  $replyText.textContent = msg.text.length > 80 ? msg.text.slice(0, 80) + '…' : msg.text;
  $replyBar.classList.remove('hidden');
  $input.focus();
}

function cancelReply() {
  replyTo = null;
  $replyBar.classList.add('hidden');
}

// ── Context menu ───────────────────────────────────────────────────────────────
let activeContextMenu = null;

function showContextMenu(e, msg) {
  hideContextMenu();
  if (msg.is_deleted) return;

  const menu = document.createElement('div');
  menu.className = 'ctx-menu';

  const actions = [
    { icon: '↩', label: 'Ответить', fn: () => setReply(msg) },
    { icon: '📋', label: 'Копировать', fn: () => { navigator.clipboard?.writeText(msg.text).catch(()=>{}); } },
  ];
  if (msg.is_mine) {
    actions.push({ icon: '🗑', label: 'Удалить', fn: () => deleteMessage(msg.id), danger: true });
  }

  actions.forEach(a => {
    const item = document.createElement('button');
    item.className = 'ctx-item' + (a.danger ? ' danger' : '');
    item.innerHTML = `<span>${a.icon}</span> ${a.label}`;
    item.onclick = () => { a.fn(); hideContextMenu(); };
    menu.appendChild(item);
  });

  // Position
  const x = Math.min(e.clientX, window.innerWidth - 160);
  const y = Math.min(e.clientY, window.innerHeight - actions.length * 44 - 16);
  menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:1000`;

  document.body.appendChild(menu);
  activeContextMenu = menu;

  setTimeout(() => document.addEventListener('click', hideContextMenu, { once: true }), 0);
}

function hideContextMenu() {
  if (activeContextMenu) { activeContextMenu.remove(); activeContextMenu = null; }
}

// ── Emoji picker ───────────────────────────────────────────────────────────────
let _emojiOutsideListener = null;

function buildEmojiPicker() {
  if (!$emojiPicker) return;
  EMOJIS.forEach(em => {
    const btn = document.createElement('button');
    btn.className = 'emoji-btn';
    btn.textContent = em;
    btn.onclick = () => insertEmoji(em);
    $emojiPicker.appendChild(btn);
  });
}

function toggleEmojiPicker() {
  const isOpen = !$emojiPicker.classList.contains('hidden');
  if (isOpen) {
    closeEmojiPicker();
  } else {
    $emojiPicker.classList.remove('hidden');
    if (!_emojiOutsideListener) {
      _emojiOutsideListener = (e) => {
        if (!$emojiPicker.contains(e.target) && e.target.id !== 'emoji-btn') {
          closeEmojiPicker();
        }
      };
      setTimeout(() => document.addEventListener('click', _emojiOutsideListener), 0);
    }
  }
}

function closeEmojiPicker() {
  $emojiPicker.classList.add('hidden');
  if (_emojiOutsideListener) {
    document.removeEventListener('click', _emojiOutsideListener);
    _emojiOutsideListener = null;
  }
}

function insertEmoji(em) {
  const start = $input.selectionStart;
  const end = $input.selectionEnd;
  const val = $input.value;
  $input.value = val.slice(0, start) + em + val.slice(end);
  $input.selectionStart = $input.selectionEnd = start + em.length;
  $input.focus();
  closeEmojiPicker();
}

// ── Delete ────────────────────────────────────────────────────────────────────
async function deleteMessage(msgId) {
  await fetch(`/chat/messages/${msgId}`, { method: 'DELETE' });
}

// ── WS event handlers ──────────────────────────────────────────────────────────
function onIncomingMessage(data) {
  // Update conv list preview
  const conv = findConvById(data.conv_id);
  if (conv) {
    conv.last_message = {
      text: data.text,
      sender_name: data.sender_name,
      created_at: data.created_at,
      is_mine: data.is_mine,
    };
    if (data.conv_id !== currentConvId && !data.is_mine) {
      conv.unread_count = (conv.unread_count || 0) + 1;
    }
    refreshConvItem(conv);
    sortConvList();
  }

  if (data.conv_id === currentConvId) {
    appendSingleMessage(data);
    if (!data.is_mine) {
      wsSend({ type: 'read', conv_id: currentConvId });
    }
  } else if (!data.is_mine) {
    // Sound notification
    playNotifSound();
    // Browser notification
    showBrowserNotif(data);
  }

  // Update nav badge
  fetchAndUpdateNavBadge();
}

function onTyping(data) {
  const { conv_id, user_id, user_name } = data;
  if (!typingUsers.has(conv_id)) typingUsers.set(conv_id, new Map());
  typingUsers.get(conv_id).set(user_id, user_name);

  // Refresh conv preview
  const conv = findConvById(conv_id);
  if (conv) refreshConvItem(conv);

  // Show typing indicator in chat area
  if (conv_id === currentConvId) showTypingBubble(user_id, user_name);

  // Auto-clear after 4s
  const key = `${conv_id}_${user_id}`;
  if (typingTimeouts.has(key)) clearTimeout(typingTimeouts.get(key));
  typingTimeouts.set(key, setTimeout(() => {
    clearTypingEntry(conv_id, user_id);
  }, 4000));
}

function onStopTyping(data) {
  clearTypingEntry(data.conv_id, data.user_id);
}

function clearTypingEntry(conv_id, user_id) {
  typingUsers.get(conv_id)?.delete(user_id);
  const conv = findConvById(conv_id);
  if (conv) refreshConvItem(conv);
  if (conv_id === currentConvId) updateTypingBubble();
}

function showTypingBubble(userId, userName) {
  updateTypingBubble();
}

function updateTypingBubble() {
  if (!$typingEl) return;
  const typingMap = typingUsers.get(currentConvId);
  if (!typingMap || typingMap.size === 0) {
    $typingEl.classList.add('hidden');
    return;
  }
  const names = [...typingMap.values()].slice(0, 2).join(', ');
  $typingEl.querySelector('.typing-text').textContent = `${names} печатает...`;
  $typingEl.classList.remove('hidden');
  if (isAtBottom) scrollBottom(true);
}

function onRead(data) {
  if (data.conv_id !== currentConvId) return;
  // Mark all my messages in this conv as read
  document.querySelectorAll('.msg-status').forEach(el => {
    el.textContent = '✓✓';
    el.classList.add('read');
  });
}

function onOnlineStatus(data) {
  const conv = conversations.find(c => c.partner_id === data.user_id);
  if (conv) {
    conv.online = data.online;
    conv.last_seen = data.last_seen;
    refreshConvItem(conv);
    if (currentConvInfo?.partner_id === data.user_id) {
      renderChatHeader(conv);
    }
  }
}

function onDelete(data) {
  const bubble = document.getElementById(`bubble-${data.msg_id}`);
  if (bubble) {
    bubble.querySelector('.msg-text').innerHTML = '<span class="msg-deleted">Сообщение удалено</span>';
    bubble.querySelector('.msg-reply-preview')?.remove();
  }
  // Also update conv preview
  const conv = findConvById(data.conv_id);
  if (conv?.last_message) {
    conv.last_message.text = 'Сообщение удалено';
    refreshConvItem(conv);
  }
}

// ── Conv list helpers ──────────────────────────────────────────────────────────
function findConvById(convId) {
  return conversations.find(c => c.id === convId);
}

function refreshConvItem(c) {
  const key = c.id ?? `dm_${c.partner_id}`;
  const el = document.querySelector(`[data-key="${key}"]`);
  if (!el) return;

  // Update online dot
  const dot = el.querySelector('.online-dot');
  if (dot) dot.className = `online-dot ${c.online ? 'is-online' : ''}`;

  // Update preview
  const preview = el.querySelector('.conv-preview');
  if (preview) preview.innerHTML = _convPreviewHtml(c);

  // Update time
  const timeEl = el.querySelector('.conv-time');
  if (timeEl && c.last_message) timeEl.textContent = fmtConvTime(c.last_message.created_at);

  // Update badge
  const badge = el.querySelector('.conv-badge');
  if (c.unread_count > 0) {
    if (badge) badge.textContent = c.unread_count > 99 ? '99+' : c.unread_count;
    else {
      const b = document.createElement('span');
      b.className = 'conv-badge';
      b.textContent = c.unread_count;
      el.querySelector('.conv-bottom').appendChild(b);
    }
  } else if (badge) badge.remove();
}

function sortConvList() {
  conversations.sort((a, b) => {
    const ta = a.last_message?.created_at || '0';
    const tb = b.last_message?.created_at || '0';
    return tb.localeCompare(ta);
  });
  renderConvList();
  // Restore active state
  if (currentConvId) {
    document.querySelector(`[data-key="${currentConvId}"]`)?.classList.add('active');
  }
}

function clearConvBadge(convId) {
  const el = document.querySelector(`[data-key="${convId}"] .conv-badge`);
  el?.remove();
}

function markRead(convId) {
  wsSend({ type: 'read', conv_id: convId });
}

// ── Notifications ─────────────────────────────────────────────────────────────
let audioCtx = null;

function playNotifSound() {
  try {
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.1, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.3);
    osc.start(audioCtx.currentTime);
    osc.stop(audioCtx.currentTime + 0.3);
  } catch(_) {}
}

function showBrowserNotif(msg) {
  if (!('Notification' in window) || Notification.permission !== 'granted') return;
  new Notification(msg.sender_name, {
    body: msg.text.length > 80 ? msg.text.slice(0, 80) + '…' : msg.text,
    icon: '/static/icons/icon-192.png',
  });
}

function requestNotifPermission() {
  if ('Notification' in window && Notification.permission === 'default') {
    Notification.requestPermission();
  }
}

async function fetchAndUpdateNavBadge() {
  try {
    const r = await fetch('/chat/unread');
    const d = await r.json();
    const badge = document.getElementById('unread-badge');
    if (badge) {
      badge.textContent = d.unread;
      badge.classList.toggle('hidden', d.unread === 0);
    }
  } catch(_) {}
}

// ── Auto-resize input ──────────────────────────────────────────────────────────
function autoResizeInput() {
  $input.style.height = 'auto';
  $input.style.height = Math.min($input.scrollHeight, 160) + 'px';
}

// ── Format helpers ─────────────────────────────────────────────────────────────
function fmtTime(isoStr) {
  const d = new Date(isoStr);
  return d.toLocaleTimeString('ru', { hour: '2-digit', minute: '2-digit' });
}

function fmtConvTime(isoStr) {
  const d = new Date(isoStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return fmtTime(isoStr);
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return 'вчера';
  if (now - d < 7 * 86400000) return DAYS_RU[d.getDay()];
  return `${d.getDate()}.${String(d.getMonth()+1).padStart(2,'0')}`;
}

function fmtDateSep(isoStr) {
  const d = new Date(isoStr);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) return 'Сегодня';
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return 'Вчера';
  return `${d.getDate()} ${MONTHS_RU[d.getMonth()]} ${d.getFullYear()}`;
}

function fmtLastSeen(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return 'только что был(а) в сети';
  if (diff < 3600000) return `был(а) в сети ${Math.floor(diff/60000)} мин. назад`;
  if (d.toDateString() === now.toDateString()) return `сегодня в ${fmtTime(isoStr)}`;
  const yesterday = new Date(now); yesterday.setDate(now.getDate() - 1);
  if (d.toDateString() === yesterday.toDateString()) return `вчера в ${fmtTime(isoStr)}`;
  return `${d.getDate()} ${MONTHS_RU[d.getMonth()]}`;
}

function linkify(text) {
  return text
    .replace(/\n/g, '<br>')
    .replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1" target="_blank" rel="noopener">$1</a>');
}

function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;');
}

// ── Compose (new chat/group) ───────────────────────────────────────────────────
let composeUsers = [];
let composeMode = 'direct';

async function openNewChatModal() {
  if (!composeUsers.length) {
    const r = await fetch('/chat/users');
    composeUsers = await r.json();
  }
  switchComposeMode('direct');
  renderComposeUsers();
  document.getElementById('compose-modal').classList.remove('hidden');
}

function closeComposeModal() {
  const modal = document.getElementById('compose-modal');
  if (modal) modal.classList.add('hidden');
}

function switchComposeMode(mode) {
  composeMode = mode;
  document.getElementById('compose-tab-direct').classList.toggle('active', mode === 'direct');
  document.getElementById('compose-tab-group').classList.toggle('active', mode === 'group');
  const nameWrap = document.getElementById('compose-name-wrap');
  if (nameWrap) nameWrap.style.display = mode === 'group' ? 'block' : 'none';
  // In direct mode only one user can be selected
  if (mode === 'direct') {
    document.querySelectorAll('.compose-user-check').forEach(cb => {
      cb.type = 'radio';
      cb.name = 'compose-user';
    });
  } else {
    document.querySelectorAll('.compose-user-check').forEach(cb => {
      cb.type = 'checkbox';
      cb.name = '';
    });
  }
}

function renderComposeUsers() {
  const list = document.getElementById('compose-user-list');
  if (!list) return;
  list.innerHTML = '';
  composeUsers.forEach(u => {
    const label = document.createElement('label');
    label.className = 'compose-user-item';
    label.innerHTML = `
      <input type="${composeMode === 'direct' ? 'radio' : 'checkbox'}" class="compose-user-check" name="compose-user" value="${u.id}">
      <div class="avatar" style="background:${u.color};width:36px;height:36px;font-size:13px;flex-shrink:0">${esc(u.initials)}</div>
      <div style="min-width:0">
        <div class="compose-user-name">${esc(u.name)}</div>
        <div class="compose-user-role">${u.role === 'manager' ? 'Менеджер' : 'Сотрудник'}</div>
      </div>
    `;
    list.appendChild(label);
  });
}

async function startCompose() {
  const checks = [...document.querySelectorAll('.compose-user-check:checked')];
  const selectedIds = checks.map(cb => parseInt(cb.value));
  if (!selectedIds.length) return;

  if (composeMode === 'direct') {
    const uid = selectedIds[0];
    const u = composeUsers.find(x => x.id === uid);
    if (!u) return;
    const c = {
      id: null, type: 'direct', name: u.name, initials: u.initials,
      color: u.color, partner_id: u.id, partner_role: u.role,
      online: u.online, last_seen: null, unread_count: 0, last_message: null,
    };
    // Check if DM already in list
    const existing = conversations.find(x => x.type === 'direct' && x.partner_id === uid);
    closeComposeModal();
    await openConv(existing || c);
  } else {
    const name = (document.getElementById('compose-group-name')?.value || '').trim() || 'Группа';
    const r = await fetch('/chat/group', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, user_ids: selectedIds }),
    });
    if (!r.ok) return;
    const conv = await r.json();
    conversations.unshift(conv);
    convMap.set(conv.id, conv);
    renderConvList();
    closeComposeModal();
    openConv(conv);
  }
}

// ── Events binding ─────────────────────────────────────────────────────────────
function bindEvents() {
  // Send on Enter (Shift+Enter = newline)
  $input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  $input.addEventListener('input', onTypingInput);
  $sendBtn.addEventListener('click', sendMessage);

  // Scroll tracking
  $messages.addEventListener('scroll', () => {
    updateScrollBtn();
    // Load more when near top
    if ($messages.scrollTop < 80 && hasMoreMessages && !isLoadingMore) {
      loadMessages(currentConvId, true);
    }
  });

  $scrollBtn?.addEventListener('click', () => scrollBottom(true));

  $loadMoreBtn?.addEventListener('click', () => {
    if (!isLoadingMore && hasMoreMessages) loadMessages(currentConvId, true);
  });

  // Cancel reply
  document.getElementById('cancel-reply')?.addEventListener('click', cancelReply);

  // Emoji toggle
  document.getElementById('emoji-btn')?.addEventListener('click', e => {
    e.stopPropagation();
    toggleEmojiPicker();
  });

  // Search
  $searchInput?.addEventListener('input', renderConvList);

  // Keyboard: Escape closes context menu / emoji
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      hideContextMenu();
      closeEmojiPicker();
      cancelReply();
      closeComposeModal();
    }
  });

  // Request browser notification permission
  requestNotifPermission();
}

// ── Visual Viewport handler (iOS keyboard & browser-chrome awareness) ─────────
// On iOS Safari the CSS dvh unit doesn't account for the URL bar on older
// versions (<15.4). visualViewport.height always reflects the real visible
// area, including keyboard open/close transitions.
function setupViewportHandler() {
  const vv = window.visualViewport;
  if (!vv) return;

  const mc = document.querySelector('.main-content');
  if (!mc) return;

  let rafId = null;

  function sync() {
    if (rafId) return;
    rafId = requestAnimationFrame(() => {
      rafId = null;
      if (window.innerWidth > 768) {
        mc.style.height = '';
        return;
      }
      // vv.height = visible area height, automatically shrinks when keyboard opens
      // subtract tab bar (56px) so our fixed-position tab bar is not double-counted
      const h = Math.max(120, Math.round(vv.height - 56));
      mc.style.height = h + 'px';

      // After keyboard animation settles, scroll messages to bottom
      if (isAtBottom && $messages) {
        $messages.scrollTop = $messages.scrollHeight;
      }
    });
  }

  vv.addEventListener('resize', sync);
  vv.addEventListener('scroll', sync);
  window.addEventListener('resize', sync); // orientation change

  sync(); // run once immediately to correct any dvh mismatch
}
