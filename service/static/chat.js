const log = document.querySelector('#log');
const input = document.querySelector('#question');
let busy = true;
let chatId = null;
const chatList = document.querySelector('#chat-list');
const newChatButton = document.querySelector('#new-chat');

async function request(url, body) {
  const response = await fetch(url, body === undefined ? {} : {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)
  });
  const data = await response.json();
  if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求失败，请重试。');
  return data;
}

function setBusy(value) {
  busy = value;
  document.querySelectorAll('button:not(#toggle-sidebar)').forEach(element => element.disabled = value);
}

function selectChat() {
  chatList.querySelectorAll('button').forEach(button => {
    const selected = button.dataset.chatId === chatId;
    button.classList.toggle('active', selected);
    if (selected) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
}

async function refreshChats() {
  const chats = await request('/api/chats');
  chatList.replaceChildren();
  for (const chat of chats) {
    const button = node(chatList, 'button', chat.title);
    button.type = 'button';
    button.title = chat.title;
    button.dataset.chatId = chat.id;
    button.disabled = busy;
    button.onclick = () => changeChat(() => openChat(chat.id));
  }
  if (!chats.length) node(chatList, 'p', '暂无历史会话');
  selectChat();
  return chats;
}

function closeSidebar() {
  document.body.classList.remove('sidebar-open');
  document.querySelector('#toggle-sidebar').setAttribute('aria-expanded', 'false');
}

function newChat() {
  chatId = null;
  sessionStorage.removeItem('aftercare-chat');
  input.value = '';
  log.replaceChildren();
  document.querySelector('main').classList.remove('chatting');
  selectChat();
  closeSidebar();
  input.focus();
}

async function openChat(id) {
  const chat = await request('/api/chats/' + id);
  chatId = id;
  // 每个标签页保存自己的选择；刷新恢复原聊天，切换不会影响其他标签页。
  sessionStorage.setItem('aftercare-chat', id);
  selectChat();
  closeSidebar();
  input.value = '';
  log.replaceChildren();
  document.querySelector('main').classList.toggle('chatting', chat.turns.length > 0);
  for (const turn of chat.turns) {
    log.querySelectorAll('article button').forEach(button => button.remove());
    bubble(turn.message, true);
    renderReply(turn.reply);
  }
  log.scrollTop = log.scrollHeight;
}

async function changeChat(operation) {
  if (busy) return;
  setBusy(true);
  try { await operation(); }
  catch (error) { document.querySelector('main').classList.add('chatting'); bubble(error.message); }
  finally { setBusy(false); }
}

newChatButton.onclick = () => changeChat(newChat);
document.querySelector('#toggle-sidebar').onclick = event => {
  const expanded = document.body.classList.toggle('sidebar-open');
  event.currentTarget.setAttribute('aria-expanded', String(expanded));
};
document.addEventListener('keydown', event => { if (event.key === 'Escape') closeSidebar(); });
function node(parent, tag, text) {
  const el = document.createElement(tag);
  el.textContent = text;
  parent.append(el);
  return el;
}
function bubble(text, user = false) {
  const el = node(log, 'article', '');
  if (user) el.className = 'user';
  node(el, 'strong', user ? '你' : '智能售后客服');
  node(el, 'p', text);
  return el;
}
const money = cents => '¥' + (cents / 100).toFixed(2);
function action(parent, text, run) {
  const button = node(parent, 'button', text);
  button.onclick = run;
}
async function send(message, ticket, buttonAction) {
  if (busy || !message.trim()) return;
  setBusy(true);
  closeSidebar();
  document.querySelector('main').classList.add('chatting');
  bubble(message, true);
  input.value = '';
  const waiting = bubble('处理中…');
  log.scrollTop = log.scrollHeight;
  const previous = [...document.querySelectorAll('article button')];
  try {
    if (!chatId) {
      const chat = await request('/api/chats', {});
      chatId = chat.id;
      sessionStorage.setItem('aftercare-chat', chatId);
    }
    const data = await request(ticket ? '/api/refunds/confirm' : '/api/chat',
      ticket ? {chat_id: chatId, ticket} : {chat_id: chatId, message, action: buttonAction});
    previous.forEach(b => b.remove());
    renderReply(ticket ? {text: data.id + ' · ' + data.status} : data);
    await refreshChats();
  } catch (err) { bubble(err.message); }
  finally {
    waiting.remove();
    setBusy(false);
    log.scrollTop = log.scrollHeight;
  }
}
function renderReply(data) {
  const el = bubble(data.text);
  if (data.mode) node(el, 'b', data.mode);
  for (const source of data.sources || []) {
    const quote = node(el, 'blockquote', '');
    node(quote, 'strong', source.title);
    node(quote, 'p', source.excerpt);
  }
  for (const o of data.orders || []) {
    action(el, [o.product, money(o.cents), o.delivered ? '签收于 ' + o.delivered : '运输中', o.id].join(' · '),
      () => send(o.id, null, {kind:"select_order", order_id:o.id}));
  }
  if (data.card) {
    const c = data.card;
    node(el, 'p', [c.order_id, '整单退款 ' + money(c.cents), '原因：' + c.reason].join('\n'));
    action(el, '确认提交', () => send('确认提交', c.ticket));
    action(el, '取消', () => send('取消', null, {kind:'cancel_pending'}));
  }
}

document.querySelectorAll('[data-ask]').forEach(b => b.onclick = () => send(b.dataset.ask));
document.querySelector('form').onsubmit = event => {event.preventDefault(); send(input.value);};

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    input.form.requestSubmit();
  }
});

setBusy(true);
try {
  const chats = await refreshChats();
  const saved = sessionStorage.getItem('aftercare-chat');
  if (chats.some(chat => chat.id === saved)) await openChat(saved);
  else newChat();
} catch (error) {
  document.querySelector('main').classList.add('chatting');
  bubble(error.message);
} finally {
  setBusy(false);
}
