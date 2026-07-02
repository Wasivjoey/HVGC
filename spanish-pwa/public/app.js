'use strict';

/* ------------------------------------------------------------------ *
 * Español para Todos — client app (vanilla JS SPA)
 * ------------------------------------------------------------------ */

const API = {
  token: localStorage.getItem('token') || null,
  async call(method, path, body) {
    const headers = { 'Content-Type': 'application/json' };
    if (this.token) headers.Authorization = 'Bearer ' + this.token;
    const res = await fetch('/api' + path, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* no body */ }
    if (!res.ok) throw new Error((data && data.error) || 'Something went wrong');
    return data;
  },
  setToken(t) { this.token = t; if (t) localStorage.setItem('token', t); else localStorage.removeItem('token'); },
};

const State = {
  user: null,
  curriculum: null,
  progress: null,
};

const el = document.getElementById('app');
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => t.classList.remove('show'), 2200);
}

const todayKey = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};

/* ------------------------------------------------------------------ *
 * Text-to-speech (speaking model) + speech recognition (practice)
 * ------------------------------------------------------------------ */
const Speech = {
  voice: null,
  init() {
    if (!('speechSynthesis' in window)) return;
    const pick = () => {
      const voices = speechSynthesis.getVoices();
      this.voice =
        voices.find((v) => /es-MX/i.test(v.lang)) ||
        voices.find((v) => /es-US/i.test(v.lang)) ||
        voices.find((v) => /es-ES/i.test(v.lang)) ||
        voices.find((v) => /^es/i.test(v.lang)) ||
        null;
    };
    pick();
    speechSynthesis.onvoiceschanged = pick;
  },
  say(text, rate = 0.9) {
    if (!('speechSynthesis' in window)) { toast('Audio not supported on this device'); return; }
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = 'es-MX';
    u.rate = rate;
    if (this.voice) u.voice = this.voice;
    speechSynthesis.speak(u);
  },
  get canListen() {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  },
  listen(onResult, onEnd) {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SR) { onEnd && onEnd(); return null; }
    const rec = new SR();
    rec.lang = 'es-MX';
    rec.interimResults = false;
    rec.maxAlternatives = 3;
    rec.onresult = (e) => {
      const alts = Array.from(e.results[0]).map((r) => r.transcript);
      onResult(alts);
    };
    rec.onerror = () => { onEnd && onEnd(); };
    rec.onend = () => { onEnd && onEnd(); };
    rec.start();
    return rec;
  },
};

// Loose comparison for speaking/writing checks (ignore accents, case, punctuation).
function normalize(s) {
  return String(s)
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/[¿?¡!.,;:]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
}

/* ------------------------------------------------------------------ *
 * Auth views
 * ------------------------------------------------------------------ */
function renderAuth(mode = 'login') {
  const isLogin = mode === 'login';
  el.innerHTML = `
    <div class="auth-wrap">
      <div class="auth-card">
        <div class="brand">
          <div class="logo">🌅</div>
          <h1>Español para Todos</h1>
          <p>Speak, read &amp; write Spanish in 5 months</p>
        </div>
        <div id="authErr"></div>
        <form id="authForm">
          <div class="field">
            <label>Username</label>
            <input name="username" autocomplete="username" required minlength="3" placeholder="e.g. sofia" />
          </div>
          ${isLogin ? '' : `
          <div class="field">
            <label>Learner's name <span class="muted">(shown on the dashboard)</span></label>
            <input name="learnerName" placeholder="Who is learning?" />
          </div>
          <div class="field">
            <label>Learner's level</label>
            <select name="ageBand">
              <option value="Little one (3–6)">Little one (3–6)</option>
              <option value="Kid (7–12)">Kid (7–12)</option>
              <option value="Teen (13–17)">Teen (13–17)</option>
              <option value="Adult (18+)" selected>Adult (18+)</option>
            </select>
          </div>`}
          <div class="field">
            <label>Password</label>
            <input name="password" type="password" autocomplete="${isLogin ? 'current-password' : 'new-password'}" required minlength="6" placeholder="At least 6 characters" />
          </div>
          <button class="btn btn-primary" type="submit">${isLogin ? 'Log in' : 'Create account'}</button>
        </form>
        <div class="switch">
          ${isLogin
            ? `New here? <a id="toReg">Create an account</a>`
            : `Already have an account? <a id="toLogin">Log in</a>`}
        </div>
      </div>
    </div>`;

  $('#toReg') && ($('#toReg').onclick = () => renderAuth('register'));
  $('#toLogin') && ($('#toLogin').onclick = () => renderAuth('login'));

  $('#authForm').onsubmit = async (e) => {
    e.preventDefault();
    const btn = $('button[type=submit]', e.target);
    btn.disabled = true; btn.textContent = 'Please wait…';
    const fd = new FormData(e.target);
    const payload = Object.fromEntries(fd.entries());
    try {
      const data = await API.call('POST', isLogin ? '/login' : '/register', payload);
      API.setToken(data.token);
      State.user = data.user;
      await boot();
    } catch (err) {
      $('#authErr').innerHTML = `<div class="error">${esc(err.message)}</div>`;
      btn.disabled = false; btn.textContent = isLogin ? 'Log in' : 'Create account';
    }
  };
}

/* ------------------------------------------------------------------ *
 * Data helpers
 * ------------------------------------------------------------------ */
function allLessons() {
  const list = [];
  for (const w of State.curriculum.weeks) for (const l of w.lessons) list.push(l);
  return list;
}
function nextLesson() {
  const done = State.progress.completed || {};
  return allLessons().find((l) => !done[l.id]) || null;
}
function isDone(id) { return !!(State.progress.completed && State.progress.completed[id]); }

async function refreshProgress() {
  State.progress = await API.call('GET', '/progress');
}

/* ------------------------------------------------------------------ *
 * Dashboard
 * ------------------------------------------------------------------ */
function renderDashboard() {
  const p = State.progress;
  const u = State.user;
  const name = u.learnerName || u.username;
  const pct = p.totalLessons ? Math.round((p.completedCount / p.totalLessons) * 100) : 0;
  const next = nextLesson();

  // last 7 days activity dots
  const actMap = {};
  for (const a of p.activity) actMap[a.day] = a;
  const dayLabels = ['Su', 'Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa'];
  let dots = '';
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
    const on = actMap[key] && actMap[key].lessons_completed > 0;
    dots += `<div class="dot ${on ? 'on' : ''}"><span>${on ? '✓' : ''}</span><small>${dayLabels[d.getDay()]}</small></div>`;
  }

  el.innerHTML = `
    <div class="topbar">
      <div class="who">
        <div class="av">${esc(name.slice(0, 1).toUpperCase())}</div>
        <div><small>¡Hola!</small><strong>${esc(name)}</strong></div>
      </div>
      <button class="linkbtn" id="logout">Log out</button>
    </div>

    ${next ? `
    <div class="card today">
      <span class="pill">Semana ${next.week} · Día ${next.day}${next.isReview ? ' · Repaso' : ''}</span>
      <h2>${esc(next.title)}</h2>
      <div class="muted">${esc(next.titleEn)} · ${esc(next.level)}</div>
      <button class="btn btn-primary" id="startNext">${p.completedCount === 0 ? 'Start learning →' : 'Continue →'}</button>
    </div>` : `
    <div class="card today">
      <span class="pill">¡Felicidades!</span>
      <h2>You finished all 5 months! 🎉</h2>
      <div class="muted">Revisit any lesson below to keep practicing.</div>
    </div>`}

    <div class="card">
      <div class="stats">
        <div class="stat"><div class="n">${p.streak}</div><div class="l">🔥 day streak</div></div>
        <div class="stat"><div class="n">${p.completedCount}</div><div class="l">lessons done</div></div>
        <div class="stat"><div class="n">${pct}%</div><div class="l">of course</div></div>
      </div>
      <div style="margin-top:14px">
        <div class="bar"><i style="width:${pct}%"></i></div>
        <div class="muted" style="margin-top:6px">${p.completedCount} of ${p.totalLessons} lessons · about ${p.totalMinutes} min practiced</div>
      </div>
      <h3 style="margin-top:16px">This week</h3>
      <div class="streak-row">${dots}</div>
    </div>

    <div id="curriculum"></div>
  `;

  $('#logout').onclick = () => {
    API.setToken(null); State.user = null; renderAuth('login');
  };
  if (next) $('#startNext').onclick = () => openLesson(next.id);
  renderCurriculum();
}

function renderCurriculum() {
  const wrap = $('#curriculum');
  const done = State.progress.completed || {};
  let html = '';
  let curMonth = 0;
  for (const w of State.curriculum.weeks) {
    if (w.month !== curMonth) {
      curMonth = w.month;
      html += `<div class="month-h">Mes ${curMonth} · Month ${curMonth}</div>`;
    }
    const total = w.lessons.length;
    const doneCount = w.lessons.filter((l) => done[l.id]).length;
    const open = w.lessons.some((l) => !done[l.id]) && w.lessons.some((l) => done[l.id]);
    html += `
      <details class="week" ${open ? 'open' : ''}>
        <summary>
          <div class="wtitle"><strong>Semana ${w.week}: ${esc(w.theme)}</strong><small>${esc(w.themeEn)} · ${esc(w.level)}</small></div>
          <div class="wmeta">${doneCount}/${total}</div>
        </summary>
        <div class="lessons">
          ${w.lessons.map((l) => `
            <div class="lesson-row ${done[l.id] ? 'done' : ''}" data-id="${l.id}">
              <div class="ck">${done[l.id] ? '✓' : ''}</div>
              <div class="lx">
                <strong>Día ${l.day}: ${esc(l.title)} ${l.isReview ? '<span class="badge-review">REPASO</span>' : ''}</strong>
                <small>${esc(l.titleEn)}${done[l.id] ? ` · best ${done[l.id].score}%` : ''}</small>
              </div>
              <div class="go">›</div>
            </div>`).join('')}
        </div>
      </details>`;
  }
  wrap.innerHTML = html;
  wrap.querySelectorAll('.lesson-row').forEach((row) => {
    row.onclick = () => openLesson(row.dataset.id);
  });
}

/* ------------------------------------------------------------------ *
 * Lesson player
 * ------------------------------------------------------------------ */
function findLesson(id) {
  for (const w of State.curriculum.weeks) {
    const l = w.lessons.find((x) => x.id === id);
    if (l) return l;
  }
  return null;
}

// Build an ordered list of interactive steps from a lesson.
function buildSteps(lesson) {
  const steps = [];
  const vocab = lesson.vocab;

  // 1) Teach each word: read + hear + (optionally) speak.
  vocab.forEach((v) => {
    steps.push({ type: 'teach', v });
  });

  // 2) Speaking practice (if the browser supports recognition) on a few words.
  const speakSet = vocab.slice(0, Math.min(3, vocab.length));
  speakSet.forEach((v) => steps.push({ type: 'speak', v }));

  // 3) Listening → multiple choice (hear Spanish, pick English).
  vocab.slice(0, Math.min(4, vocab.length)).forEach((v) => {
    steps.push({ type: 'quiz', v, mode: 'listen', options: makeOptions(vocab, v, 'en') });
  });

  // 4) Reading → multiple choice (see Spanish, pick English).
  vocab.forEach((v) => {
    steps.push({ type: 'quiz', v, mode: 'read', options: makeOptions(vocab, v, 'en') });
  });

  // 5) Writing → type the Spanish word for an English prompt.
  vocab.slice(0, Math.min(5, vocab.length)).forEach((v) => {
    steps.push({ type: 'write', v });
  });

  // 6) Phrases (read + hear).
  (lesson.phrases || []).forEach((ph) => steps.push({ type: 'phrase', ph }));

  return steps;
}

function makeOptions(vocab, correct, key) {
  const pool = vocab.filter((x) => x[key] !== correct[key]);
  // shuffle pool
  for (let i = pool.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [pool[i], pool[j]] = [pool[j], pool[i]];
  }
  const opts = [correct, ...pool.slice(0, 3)];
  for (let i = opts.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [opts[i], opts[j]] = [opts[j], opts[i]];
  }
  return opts;
}

const Lesson = { id: null, steps: [], i: 0, correct: 0, gradable: 0, startedAt: 0 };

function openLesson(id) {
  const lesson = findLesson(id);
  if (!lesson) return;
  Lesson.id = id;
  Lesson.steps = buildSteps(lesson);
  Lesson.i = 0;
  Lesson.correct = 0;
  Lesson.gradable = Lesson.steps.filter((s) => s.type === 'quiz' || s.type === 'write' || s.type === 'speak').length;
  Lesson.startedAt = Date.now();
  Lesson.lesson = lesson;
  window.scrollTo(0, 0);
  renderStep();
}

function closeLesson() {
  speechSynthesis && speechSynthesis.cancel();
  renderDashboard();
}

function renderStep() {
  if (Lesson.i >= Lesson.steps.length) return finishLesson();
  const step = Lesson.steps[Lesson.i];
  const total = Lesson.steps.length;
  const stepsBar = Array.from({ length: total }, (_, k) =>
    `<i class="${k <= Lesson.i ? 'on' : ''}"></i>`).join('');

  let body = '';
  if (step.type === 'teach') body = viewTeach(step.v);
  else if (step.type === 'speak') body = viewSpeak(step.v);
  else if (step.type === 'quiz') body = viewQuiz(step);
  else if (step.type === 'write') body = viewWrite(step.v);
  else if (step.type === 'phrase') body = viewPhrase(step.ph);

  el.innerHTML = `
    <div class="player">
      <div class="head">
        <button class="x" id="closeL">✕</button>
        <div class="muted" style="color:#fff">${Lesson.i + 1} / ${total}</div>
        <div style="width:40px"></div>
      </div>
      <div class="progress-steps">${stepsBar}</div>
      <div class="stage" id="stage">${body}</div>
    </div>`;

  $('#closeL').onclick = closeLesson;
  wireStep(step);
}

function advance() { Lesson.i++; renderStep(); }

function viewTeach(v) {
  return `
    <div class="kicker">Nueva palabra · New word</div>
    <div class="es">${esc(v.es)}</div>
    <div class="en">${esc(v.en)}</div>
    <button class="speak-btn" data-say="${esc(v.es)}">🔊 Escuchar</button>
    <div class="example">
      <div class="exes" data-say="${esc(v.exampleEs)}">“${esc(v.exampleEs)}” 🔊</div>
      <div class="exen">${esc(v.exampleEn)}</div>
    </div>
    <div class="stage-actions">
      <button class="btn btn-primary" id="next">Continuar →</button>
    </div>`;
}

function viewPhrase(ph) {
  return `
    <div class="kicker">Frase útil · Useful phrase</div>
    <div class="es" style="font-size:26px">${esc(ph.es)}</div>
    <div class="en">${esc(ph.en)}</div>
    <button class="speak-btn" data-say="${esc(ph.es)}">🔊 Escuchar</button>
    <div class="stage-actions">
      <button class="btn btn-primary" id="next">Continuar →</button>
    </div>`;
}

function viewSpeak(v) {
  const can = Speech.canListen;
  return `
    <div class="kicker">Habla · Speak it</div>
    <div class="es">${esc(v.es)}</div>
    <div class="en">${esc(v.en)}</div>
    <button class="speak-btn" data-say="${esc(v.es)}">🔊 Oír el modelo</button>
    <div class="mt">
      ${can
        ? `<button class="speak-btn mic-btn" id="mic">🎤 Toca y habla</button>
           <div class="feedback" id="spkFb"></div>`
        : `<div class="muted">Speech recognition isn't available here — say it out loud, then continue.</div>`}
    </div>
    <div class="stage-actions">
      <button class="btn btn-ghost" id="skip">Saltar</button>
      <button class="btn btn-primary" id="next" ${can ? 'style="display:none"' : ''}>Continuar →</button>
    </div>`;
}

function viewQuiz(step) {
  const prompt = step.mode === 'listen'
    ? `<div class="kicker">Escucha y elige · Listen &amp; choose</div>
       <button class="speak-btn" data-say="${esc(step.v.es)}" id="replay">🔊 Reproducir</button>`
    : `<div class="kicker">Lee y elige · Read &amp; choose</div>
       <div class="es">${esc(step.v.es)}</div>`;
  return `
    ${prompt}
    <div class="options">
      ${step.options.map((o) => `<button class="option" data-en="${esc(o.en)}">${esc(o.en)}</button>`).join('')}
    </div>`;
}

function viewWrite(v) {
  return `
    <div class="kicker">Escribe en español · Write in Spanish</div>
    <div class="en" style="font-size:22px;margin-top:10px">${esc(v.en)}</div>
    <button class="speak-btn" data-say="${esc(v.es)}">🔊 Pista</button>
    <input class="write-input mt" id="writeIn" autocomplete="off" autocapitalize="off" autocorrect="off" spellcheck="false" placeholder="tu respuesta…" />
    <div class="accents">
      ${['á','é','í','ó','ú','ñ','ü','¿','¡'].map((c) => `<button data-ch="${c}">${c}</button>`).join('')}
    </div>
    <div class="feedback" id="writeFb"></div>
    <div class="stage-actions">
      <button class="btn btn-primary" id="check">Revisar</button>
    </div>`;
}

function wireStep(step) {
  // wire all speak buttons
  el.querySelectorAll('[data-say]').forEach((b) => {
    b.addEventListener('click', () => Speech.say(b.getAttribute('data-say')));
  });

  if (step.type === 'teach' || step.type === 'phrase') {
    // auto-play the word once
    Speech.say(step.type === 'teach' ? step.v.es : step.ph.es);
    $('#next').onclick = advance;
  }

  if (step.type === 'speak') {
    Speech.say(step.v.es);
    const skip = $('#skip'); if (skip) skip.onclick = advance;
    const next = $('#next'); if (next) next.onclick = advance;
    const mic = $('#mic');
    if (mic) {
      mic.onclick = () => {
        const fb = $('#spkFb');
        fb.textContent = 'Escuchando…'; fb.className = 'feedback';
        mic.classList.add('rec');
        Speech.listen(
          (alts) => {
            const target = normalize(step.v.es);
            const ok = alts.some((a) => normalize(a) === target || normalize(a).includes(target));
            if (ok) {
              Lesson.correct++;
              fb.textContent = '¡Muy bien! 🎉'; fb.className = 'feedback ok';
              setTimeout(advance, 900);
            } else {
              fb.innerHTML = `Escuché: “${esc(alts[0] || '—')}”. Intenta otra vez o continúa.`;
              fb.className = 'feedback no';
              $('#next').style.display = '';
            }
          },
          () => { mic.classList.remove('rec'); }
        );
      };
    }
  }

  if (step.type === 'quiz') {
    if (step.mode === 'listen') Speech.say(step.v.es);
    let answered = false;
    el.querySelectorAll('.option').forEach((btn) => {
      btn.onclick = () => {
        if (answered) return;
        answered = true;
        const chosen = btn.getAttribute('data-en');
        const correct = step.v.en;
        el.querySelectorAll('.option').forEach((b) => {
          b.disabled = true;
          if (b.getAttribute('data-en') === correct) b.classList.add('correct');
        });
        if (chosen === correct) {
          Lesson.correct++;
          Speech.say(step.v.es);
        } else {
          btn.classList.add('wrong');
        }
        setTimeout(advance, 1000);
      };
    });
  }

  if (step.type === 'write') {
    const input = $('#writeIn');
    input.focus();
    el.querySelectorAll('.accents button').forEach((b) => {
      b.onclick = () => {
        input.value += b.getAttribute('data-ch');
        input.focus();
      };
    });
    const check = () => {
      const fb = $('#writeFb');
      const ok = normalize(input.value) === normalize(step.v.es);
      if (ok) {
        Lesson.correct++;
        fb.textContent = '¡Correcto! ✓'; fb.className = 'feedback ok';
        Speech.say(step.v.es);
        input.disabled = true;
        $('#check').textContent = 'Continuar →';
        $('#check').onclick = advance;
      } else {
        fb.innerHTML = `Casi. La respuesta es <b>${esc(step.v.es)}</b>.`;
        fb.className = 'feedback no';
        $('#check').textContent = 'Continuar →';
        $('#check').onclick = advance;
      }
    };
    $('#check').onclick = check;
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') $('#check').click(); });
  }
}

async function finishLesson() {
  const score = Lesson.gradable ? Math.round((Lesson.correct / Lesson.gradable) * 100) : 100;
  const minutes = Math.max(1, Math.round((Date.now() - Lesson.startedAt) / 60000));
  const stars = score >= 90 ? '⭐⭐⭐' : score >= 60 ? '⭐⭐' : '⭐';
  const emoji = score >= 90 ? '🏆' : score >= 60 ? '🎉' : '💪';

  el.innerHTML = `
    <div class="player">
      <div class="stage result">
        <div class="big">${emoji}</div>
        <div class="kicker">Lección completa</div>
        <div style="font-size:30px;margin:6px 0">${stars}</div>
        <div class="score">${score}%</div>
        <div class="muted mt">You practiced for about ${minutes} min. ¡Buen trabajo!</div>
        <div class="stage-actions" style="flex-direction:column">
          <button class="btn btn-primary" id="cont">Continuar</button>
        </div>
      </div>
    </div>`;

  $('#cont').disabled = true;
  try {
    await API.call('POST', '/progress/complete', {
      lessonId: Lesson.id, score, minutes, day: todayKey(),
    });
    await refreshProgress();
  } catch (err) {
    toast(err.message);
  }
  const cont = $('#cont');
  cont.disabled = false;
  cont.onclick = () => {
    const nxt = nextLesson();
    if (nxt && nxt.id !== Lesson.id) openLesson(nxt.id);
    else renderDashboard();
  };
}

/* ------------------------------------------------------------------ *
 * Boot
 * ------------------------------------------------------------------ */
async function boot() {
  el.innerHTML = `<div class="auth-wrap"><div class="muted" style="color:#fff">Cargando…</div></div>`;
  try {
    if (!State.curriculum) State.curriculum = await API.call('GET', '/curriculum');
    if (API.token && !State.user) {
      const me = await API.call('GET', '/me');
      State.user = me.user;
    }
    if (!State.user) { renderAuth('login'); return; }
    await refreshProgress();
    renderDashboard();
  } catch (err) {
    // token invalid/expired
    API.setToken(null); State.user = null;
    renderAuth('login');
  }
}

Speech.init();
boot();

if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/service-worker.js').catch(() => {});
  });
}
