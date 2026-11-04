const log = document.querySelector('#log');
const input = document.querySelector('#question');
let busy = false;
function node(parent, tag, text) {
  const el = document.createElement(tag);
  el.textContent = text;
  parent.append(el);
  return el;
}
function bubble(text, user = false) {
  const el = node(log, 'article', '');
  if (user) el.className = 'user';
  node(el, 'strong', user ? '你' : '云杉客服');
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
  busy = true;
  document.querySelector('main').classList.add('chatting');
  bubble(message, true);
  input.value = '';
  const waiting = bubble('处理中…');
  log.scrollTop = log.scrollHeight;
  const buttons = document.querySelectorAll('button');
  buttons.forEach(b => b.disabled = true);
  try {
    const response = await fetch(ticket ? '/api/refunds/confirm' : '/api/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body:JSON.stringify(ticket ? {ticket} : {message, action:buttonAction})
    });
    const data = await response.json();
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '请求失败，请重试。');
    log.querySelectorAll('button').forEach(b => b.remove());
    const el = bubble(ticket ? data.id + ' · ' + data.status : data.text);
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
  } catch (err) { bubble(err.message); }
  finally {
    waiting.remove();
    buttons.forEach(b => b.disabled = false);
    busy = false;
    log.scrollTop = log.scrollHeight;
  }
}
document.querySelectorAll('nav button').forEach(b => b.onclick = () => send(b.dataset.ask));
document.querySelector('form').onsubmit = event => {event.preventDefault(); send(input.value);};

input.addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    input.form.requestSubmit();
  }
});
