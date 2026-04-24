// ═══ XEM BÀI HỌC JS ═══

// ── Render Markdown đơn giản ──
function renderMarkdown(text) {
  if (!text) return '<p style="color:var(--neutral-400);font-style:italic;">Không có nội dung.</p>';
  let html = text
    // Code blocks
    .replace(/```(\w*)\n?([\s\S]*?)```/g, (_, lang, code) =>
      `<pre><code>${code.replace(/</g,'&lt;').replace(/>/g,'&gt;').trim()}</code></pre>`)
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Headings
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold & italic
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Blockquote
    .replace(/^> (.+)$/gm, '<blockquote>$1</blockquote>')
    // HR
    .replace(/^---$/gm, '<hr>')
    // Tables (simple)
    .replace(/^\|(.+)\|$/gm, (line) => {
      if (line.includes('---')) return '';
      const cells = line.slice(1,-1).split('|').map(c => c.trim());
      const isHeader = false;
      return `<tr>${cells.map(c => `<td>${c}</td>`).join('')}</tr>`;
    })
    // Lists
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    .replace(/^\d+\. (.+)$/gm, '<li>$1</li>')
    // Paragraphs
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');

  // Wrap li items in ul
  html = html.replace(/(<li>.*?<\/li>)+/gs, m => `<ul>${m}</ul>`);
  // Wrap tr items in table
  html = html.replace(/(<tr>.*?<\/tr>)+/gs, m => `<table>${m}</table>`);

  return `<p>${html}</p>`;
}

// ── Render all materials ──
document.querySelectorAll('.material-content').forEach(el => {
  const content = el.dataset.content;
  const body = el.querySelector('.rendered-content');
  if (body) body.innerHTML = renderMarkdown(content);
});

// Tải nhắc học AI ở trang bài học: nếu user gián đoạn >= 2 ngày thì hiện cảnh báo nhẹ.
loadLessonAIReminder();
// Nếu đi từ tab AI với query from=ai-plan thì hiển thị banner định hướng ôn tập.
showAIPlanEntryBanner();

// ── Toggle material card ──
function toggleMaterialCard(header) {
  const content = header.closest('.material-card').querySelector('.material-content');
  const btn = header.querySelector('.material-collapse-btn');
  btn.classList.toggle('collapsed');
  content.classList.toggle('hidden');
}

// Keep old name for backward compat
function toggleMaterial(btn) {
  const content = btn.closest('.material-card').querySelector('.material-content');
  btn.classList.toggle('collapsed');
  content.classList.toggle('hidden');
}

// ── Lesson tab switching ──
function switchLessonTab(tab, btn) {
  document.querySelectorAll('.ltab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.ltab-panel').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  document.getElementById(`ltab-${tab}`)?.classList.add('active');
}

// ══════════════════════════════════════════
// EXERCISE SYSTEM
// ══════════════════════════════════════════

let exerciseStarted = false;
let answers = {};
let totalQuestions = 0;

function startExercise() {
  exerciseStarted = true;
  answers = {};
  totalQuestions = document.querySelectorAll('.exercise-card').length;

  // Reset all cards
  document.querySelectorAll('.exercise-card').forEach(card => {
    card.classList.remove('answered-correct','answered-wrong');
    card.querySelectorAll('.ex-opt').forEach(opt => {
      opt.disabled = false;
      opt.classList.remove('correct','wrong');
    });
    const id = card.id.replace('ex-','');
    document.getElementById(`ex-status-${id}`).textContent = '';
    document.getElementById(`ex-exp-${id}`)?.classList.add('hidden');
  });

  document.getElementById('exercise-result')?.classList.add('hidden');
  showToast('Bài tập đã bắt đầu! Chọn đáp án cho mỗi câu.', 'success');
}

function selectAnswer(exId, letter, btn) {
  if (!exerciseStarted) {
    showToast('Nhấn "Bắt Đầu Làm Bài" trước!', 'error');
    return;
  }
  const card = document.getElementById(`ex-${exId}`);
  const correct = card.dataset.correct;
  const isCorrect = letter === correct;

  // Disable all options
  card.querySelectorAll('.ex-opt').forEach(opt => {
    opt.disabled = true;
    if (opt.dataset.letter === correct) opt.classList.add('correct');
    if (opt.dataset.letter === letter && !isCorrect) opt.classList.add('wrong');
  });

  // Show status
  const statusEl = document.getElementById(`ex-status-${exId}`);
  if (statusEl) {
    statusEl.textContent = isCorrect ? '✅ Đúng!' : '❌ Sai';
    statusEl.style.color = isCorrect ? '#10b981' : '#ef4444';
  }

  // Show explanation
  document.getElementById(`ex-exp-${exId}`)?.classList.remove('hidden');

  // Card highlight
  card.classList.add(isCorrect ? 'answered-correct' : 'answered-wrong');

  // Record answer
  answers[exId] = { isCorrect, selected: letter };

  // Check if all answered
  if (Object.keys(answers).length === totalQuestions) {
    setTimeout(showExerciseResult, 600);
  }
}

function showExerciseResult() {
  const correct = Object.values(answers).filter(a => a && a.isCorrect).length;
  const total   = totalQuestions;
  const pct     = Math.round((correct / total) * 100);

  const resultEl = document.getElementById('exercise-result');
  const scoreEl  = document.getElementById('result-score');
  const msgEl    = document.getElementById('result-msg');

  scoreEl.textContent = `${correct}/${total} — ${pct}%`;
  let msg = '';
  if (pct === 100) msg = '🏆 Xuất sắc! Bạn đã trả lời đúng tất cả câu hỏi!';
  else if (pct >= 80) msg = '🎉 Tuyệt vời! Bạn nắm vững kiến thức bài học này.';
  else if (pct >= 60) msg = '👍 Khá tốt! Hãy xem lại những câu trả lời sai nhé.';
  else msg = '📖 Hãy đọc lại tài liệu và thử lại!';
  msgEl.textContent = msg;

  resultEl.classList.remove('hidden');
  resultEl.scrollIntoView({ behavior: 'smooth', block: 'center' });

  submitExerciseAttempt();
}

function retryExercise() {
  startExercise();
  document.querySelector('.exercise-card')?.scrollIntoView({ behavior: 'smooth' });
}

async function submitExerciseAttempt() {
  const aiEl = document.getElementById('exercise-ai-feedback');
  const analyticsEl = document.getElementById('exercise-analytics');
  const wrongEl = document.getElementById('exercise-wrong-insights');
  const chartEl = document.getElementById('exercise-progress-chart');
  const planEl = document.getElementById('exercise-study-plan');
  const planProgressEl = document.getElementById('exercise-study-plan-progress');
  const planHistoryEl = document.getElementById('exercise-study-plan-history');
  if (aiEl) aiEl.textContent = 'Đang phân tích kết quả và tạo gợi ý AI...';
  if (analyticsEl) analyticsEl.innerHTML = '';
  if (wrongEl) wrongEl.innerHTML = '';
  if (chartEl) chartEl.innerHTML = '';
  if (planEl) planEl.innerHTML = '';
  if (planProgressEl) planProgressEl.innerHTML = '';
  if (planHistoryEl) planHistoryEl.innerHTML = '';

  try {
    const answerPayload = {};
    Object.entries(answers).forEach(([exId, info]) => {
      answerPayload[exId] = info?.selected || '';
    });

    const fd = new FormData();
    fd.append('lesson_id', LESSON_ID);
    fd.append('answers_json', JSON.stringify(answerPayload));

    const res = await fetch('/submit-lesson-quiz', { method: 'POST', body: fd });
    const payload = await res.json();
    if (!payload.success || !payload.data) {
      throw new Error(payload.message || 'Nộp kết quả thất bại');
    }
    const data = payload.data;

    if (aiEl) {
      aiEl.innerHTML = `<strong>🤖 AI hỗ trợ học tập:</strong> ${data.ai_feedback || 'Chưa có gợi ý.'}`;
    }

    if (analyticsEl) {
      analyticsEl.innerHTML = [
        metricCard('Tỷ lệ đạt bài', `${data.score_pct}%`),
        metricCard('Số lần làm bài này', `${data.lesson_attempts}`),
        metricCard('Điểm cao nhất bài', `${data.lesson_best_score}%`),
        metricCard('Độ chính xác toàn khóa', `${data.course_accuracy_pct}%`),
        metricCard('Tiến độ khóa học', `${data.course_progress_pct}%`),
      ].join('');
    }

    // AI mini feedback theo từng câu sai (nếu có).
    if (wrongEl) {
      wrongEl.innerHTML = renderWrongInsights(data.wrong_details || []);
    }

    // Chart tiến bộ các lần làm bài gần nhất.
    if (chartEl) {
      chartEl.innerHTML = renderProgressChart(data.history_points || []);
    }

    // Kế hoạch 3 ngày để người học có hành động cụ thể ngay sau khi nộp bài.
    if (planEl) {
      planEl.innerHTML = renderStudyPlan3D(data.study_plan_3d || []);
    }
    if (planProgressEl) {
      planProgressEl.innerHTML = renderLatestPlanProgress(data.study_plan_history || []);
    }
    if (planHistoryEl) {
      planHistoryEl.innerHTML = renderStudyPlanHistory(data.study_plan_history || []);
    }

    // Nếu backend tự động mark complete (đạt >=60%), đồng bộ trạng thái ngay trên UI.
    if (data.auto_marked_complete) {
      syncLessonCompletedUI();
      showToast('🎯 Đạt từ 60%: bài học đã được tự động đánh dấu hoàn thành.', 'success');
    }
  } catch (err) {
    if (aiEl) aiEl.textContent = 'Chưa thể phân tích AI lúc này. Bạn vẫn có thể làm lại bài để cải thiện kết quả.';
  }
}

async function loadLessonAIReminder() {
  const box = document.getElementById('lesson-ai-reminder');
  if (!box) return;
  try {
    const res = await fetch('/api/ai/personalization');
    const payload = await res.json();
    const p = payload?.data;
    if (!payload?.success || !p) return;
    if (Number(p.inactivity_days || 0) < 2) return;
    const title = p.reminder?.title || '🔔 Nhắc học từ AI';
    const message = p.reminder?.message || 'Bạn đang gián đoạn việc học. Hãy quay lại với 1 bài ngắn ngay hôm nay.';
    box.innerHTML = `<strong>${escapeHtml(title)}</strong><div style="margin-top:4px;font-size:.9rem;line-height:1.5;">${escapeHtml(message)}</div>`;
    box.style.display = 'block';
  } catch {
    // Không chặn trải nghiệm học nếu API nhắc học tạm thời lỗi.
  }
}

function showAIPlanEntryBanner() {
  const box = document.getElementById('lesson-ai-plan-entry');
  if (!box) return;
  const params = new URLSearchParams(window.location.search);
  if (params.get('from') !== 'ai-plan') return;
  box.innerHTML = '<strong>🤖 Bạn đang học theo kế hoạch AI</strong><div style="margin-top:4px;font-size:.9rem;line-height:1.5;">Hãy hoàn thành bài học này và làm quiz để tiếp tục cập nhật tiến độ kế hoạch 3 ngày.</div>';
  box.style.display = 'block';
}

function metricCard(label, value) {
  return `
    <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;text-align:left;">
      <div style="font-size:.72rem;color:#64748b;font-weight:600;text-transform:uppercase;letter-spacing:.04em;">${label}</div>
      <div style="margin-top:4px;font-size:1.05rem;color:#0f172a;font-weight:800;">${value}</div>
    </div>
  `;
}

// Render AI mini cards cho các câu sai để người học biết cần ôn gì.
function renderWrongInsights(items) {
  if (!items.length) {
    return `
      <div style="background:#ecfdf5;border:1px solid #86efac;border-radius:10px;padding:10px 12px;color:#166534;">
        ✅ Bạn không có câu sai trong lần làm này.
      </div>
    `;
  }
  const cards = items.map((it, idx) => `
    <div style="background:#fff7ed;border:1px solid #fdba74;border-radius:10px;padding:10px 12px;margin-top:8px;">
      <div style="font-size:.78rem;color:#9a3412;font-weight:700;">AI mini #${idx + 1}</div>
      <div style="margin-top:4px;font-size:.92rem;color:#431407;font-weight:600;">${escapeHtml(it.question || '')}</div>
      <div style="margin-top:6px;font-size:.84rem;color:#7c2d12;">Bạn chọn: <strong>${escapeHtml(it.chosen || '')}</strong> · Đúng: <strong>${escapeHtml(it.correct || '')}</strong></div>
      ${it.correct_text ? `<div style="font-size:.84rem;color:#7c2d12;">Đáp án đúng: ${escapeHtml(it.correct_text)}</div>` : ''}
      ${it.explanation ? `<div style="margin-top:4px;font-size:.83rem;color:#9a3412;">Giải thích: ${escapeHtml(it.explanation)}</div>` : ''}
      <div style="margin-top:6px;font-size:.83rem;color:#7c2d12;"><strong>Gợi ý AI:</strong> ${escapeHtml(it.ai_tip || '')}</div>
    </div>
  `).join('');
  return `
    <div style="margin-top:6px;font-size:.86rem;color:#7c2d12;font-weight:700;">📌 Trọng tâm cần ôn theo AI</div>
    ${cards}
  `;
}

// Render chart cột mini cho các lần làm gần nhất (không dùng thư viện ngoài).
function renderProgressChart(points) {
  if (!points.length) return '';
  const bars = points.map((p) => {
    const h = Math.max(8, Math.min(100, Number(p.score_pct || 0)));
    return `
      <div style="display:flex;flex-direction:column;align-items:center;gap:6px;flex:1;min-width:54px;">
        <div style="font-size:.74rem;color:#334155;font-weight:700;">${p.score_pct}%</div>
        <div style="width:22px;height:110px;background:#e2e8f0;border-radius:8px;display:flex;align-items:flex-end;overflow:hidden;">
          <div style="width:100%;height:${h}%;background:linear-gradient(180deg,#60a5fa,#2563eb);"></div>
        </div>
        <div style="font-size:.72rem;color:#64748b;">Lần ${p.attempt_no}</div>
      </div>
    `;
  }).join('');
  return `
    <div style="margin-top:10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;">
      <div style="font-size:.82rem;color:#334155;font-weight:700;margin-bottom:8px;">📈 Tiến bộ các lần làm bài gần nhất</div>
      <div style="display:flex;gap:8px;align-items:flex-end;">
        ${bars}
      </div>
    </div>
  `;
}

function renderStudyPlan3D(items) {
  if (!items.length) return '';
  const rows = items.map((line, idx) => `
    <div style="display:flex;align-items:flex-start;gap:8px;margin-top:${idx === 0 ? 0 : 8}px;">
      <div style="min-width:60px;font-size:.78rem;color:#1d4ed8;font-weight:700;">Ngày ${idx + 1}</div>
      <div style="font-size:.86rem;color:#1e3a8a;line-height:1.5;">${escapeHtml(line)}</div>
    </div>
  `).join('');
  return `
    <div style="margin-top:10px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:10px;padding:10px 12px;">
      <div style="font-size:.82rem;color:#1e40af;font-weight:700;margin-bottom:6px;">🗓️ Kế hoạch ôn tập 3 ngày</div>
      ${rows}
    </div>
  `;
}

function renderStudyPlanHistory(rows) {
  if (!rows.length) return '';
  const cards = rows.map((row, idx) => {
    const items = Array.isArray(row.items) ? row.items : [];
    const progress = Array.isArray(row.progress) ? row.progress : [];
    const lines = items.map((line, i) => {
      const checked = progress[i] ? 'checked' : '';
      const inputId = `plan-${Number(row.plan_id || 0)}-day-${i}`;
      return `
        <label for="${inputId}" style="display:flex;align-items:flex-start;gap:8px;margin-top:${i === 0 ? 6 : 4}px;cursor:pointer;">
          <input
            id="${inputId}"
            class="plan-day-checkbox"
            type="checkbox"
            ${checked}
            onchange="toggleStudyPlanDay(${Number(row.plan_id || 0)}, ${i}, this)"
            style="margin-top:2px;"
          />
          <span style="font-size:.8rem;color:#475569;line-height:1.45;">${escapeHtml(line)}</span>
        </label>
      `;
    }).join('');
    const dateRaw = String(row.created_at || '').replace('T', ' ');
    const completedCount = progress.filter(Boolean).length;
    return `
      <div class="study-plan-card" data-plan-id="${Number(row.plan_id || 0)}" style="border:1px solid #e2e8f0;border-radius:8px;padding:8px 10px;background:#ffffff;margin-top:${idx === 0 ? 0 : 8}px;">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:center;">
          <div style="font-size:.8rem;color:#0f172a;font-weight:700;">Lần #${rows.length - idx} • Điểm ${Number(row.score_pct || 0)}% • Hoàn thành ${completedCount}/${items.length || 0} ngày</div>
          <div style="font-size:.74rem;color:#64748b;">${escapeHtml(dateRaw.slice(0, 16))}</div>
        </div>
        ${lines}
      </div>
    `;
  }).join('');
  return `
    <div style="margin-top:10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;padding:10px 12px;">
      <div style="font-size:.82rem;color:#334155;font-weight:700;margin-bottom:6px;">🧾 Lịch sử kế hoạch 3 ngày (gần nhất)</div>
      ${cards}
    </div>
  `;
}

function renderLatestPlanProgress(rows) {
  if (!rows.length) return '';
  const latest = rows[0] || {};
  const items = Array.isArray(latest.items) ? latest.items : [];
  const progress = Array.isArray(latest.progress) ? latest.progress : [];
  const total = Math.max(1, items.length);
  const done = progress.slice(0, total).filter(Boolean).length;
  const pct = Math.round((done / total) * 100);
  return `
    <div style="background:#ecfeff;border:1px solid #a5f3fc;border-radius:10px;padding:10px 12px;">
      <div id="latest-plan-progress-text" style="font-size:.82rem;color:#155e75;font-weight:700;margin-bottom:8px;">📊 Tiến độ kế hoạch gần nhất: ${done}/${total} ngày (${pct}%)</div>
      <div style="height:10px;background:#cffafe;border-radius:999px;overflow:hidden;">
        <div id="latest-plan-progress-fill" style="height:100%;width:${pct}%;background:linear-gradient(90deg,#22d3ee,#0284c7);"></div>
      </div>
    </div>
  `;
}

async function toggleStudyPlanDay(planId, dayIndex, checkboxEl) {
  const checked = !!checkboxEl?.checked;
  const fd = new FormData();
  fd.append('plan_id', String(planId));
  fd.append('day_index', String(dayIndex));
  fd.append('completed', checked ? '1' : '0');
  try {
    const res = await fetch('/lesson-study-plan/mark-day', { method: 'POST', body: fd });
    const payload = await res.json();
    if (!payload?.success) {
      throw new Error(payload?.message || 'Không thể cập nhật');
    }
    const total = Number(payload?.data?.total_days || 0);
    const done = Number(payload?.data?.completed_count || 0);
    refreshLatestPlanProgressUI();
    showToast(`Đã cập nhật kế hoạch: ${done}/${total} ngày hoàn thành.`, 'success');
  } catch (err) {
    if (checkboxEl) checkboxEl.checked = !checked;
    showToast('Không thể lưu trạng thái ngày học lúc này.', 'error');
  }
}

function refreshLatestPlanProgressUI() {
  const latestCard = document.querySelector('.study-plan-card');
  const fillEl = document.getElementById('latest-plan-progress-fill');
  const textEl = document.getElementById('latest-plan-progress-text');
  if (!latestCard || !fillEl || !textEl) return;
  const boxes = latestCard.querySelectorAll('.plan-day-checkbox');
  const total = boxes.length || 1;
  let done = 0;
  boxes.forEach((b) => { if (b.checked) done += 1; });
  const pct = Math.round((done / total) * 100);
  fillEl.style.width = `${pct}%`;
  textEl.textContent = `📊 Tiến độ kế hoạch gần nhất: ${done}/${total} ngày (${pct}%)`;
}

// Đồng bộ UI khi bài được backend tự mark complete nhờ đạt mốc quiz.
function syncLessonCompletedUI() {
  const btn = document.getElementById('complete-btn');
  if (btn) {
    btn.textContent = '✅ Đã Hoàn Thành';
    btn.classList.add('is-done');
  }
  const badge = document.getElementById('status-badge');
  if (badge) badge.textContent = '✅ Đã hoàn thành';
  const numEl = document.getElementById(`ls-num-${LESSON_ID}`);
  if (numEl) {
    numEl.textContent = '✓';
    numEl.classList.add('done');
  }
}

function escapeHtml(str) {
  return String(str || '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#039;');
}

// ══════════════════════════════════════════
// NOTES SYSTEM
// ══════════════════════════════════════════

const NOTE_KEY = `edu_note_lesson_${typeof LESSON_ID !== 'undefined' ? LESSON_ID : '0'}`;
let autoSaveTimer = null;

const noteArea = document.getElementById('lesson-note');
if (noteArea) {
  try { noteArea.value = localStorage.getItem(NOTE_KEY) || ''; } catch (e) {}
  noteArea.addEventListener('input', () => {
    clearTimeout(autoSaveTimer);
    const indicator = document.getElementById('note-autosave');
    if (indicator) indicator.textContent = '...';
    autoSaveTimer = setTimeout(() => {
      try {
        localStorage.setItem(NOTE_KEY, noteArea.value);
        if (indicator) { indicator.textContent = '✓ Đã lưu'; setTimeout(() => { indicator.textContent = ''; }, 2000); }
      } catch (e) {}
    }, 800);
  });
}

function saveNote() {
  try {
    localStorage.setItem(NOTE_KEY, noteArea.value);
    showToast('Ghi chú đã được lưu!', 'success');
  } catch (e) {
    showToast('Không thể lưu ghi chú.', 'error');
  }
}

// ── Sidebar toggle (mobile) ──
function toggleLessonSidebar() {
  document.getElementById('lesson-sidebar')?.classList.toggle('open');
}

// ── Mark complete — gọi API ──
async function markComplete() {
  const btn = document.getElementById('complete-btn');
  if (btn.classList.contains('is-done')) return;

  btn.textContent = '⏳ Đang lưu...'; btn.disabled = true;

  try {
    const fd = new FormData(); fd.append('lesson_id', LESSON_ID);
    const res  = await fetch('/mark-lesson-complete', { method: 'POST', body: fd });
    const data = await res.json();
    if (data.success) {
      btn.textContent = '✅ Đã Hoàn Thành';
      btn.classList.add('is-done');
      document.getElementById('status-badge').textContent = '✅ Đã hoàn thành';
      // cập nhật sidebar
      const numEl = document.getElementById(`ls-num-${LESSON_ID}`);
      if (numEl) { numEl.textContent = '✓'; numEl.classList.add('done'); }
      // cập nhật progress bar
      updateSidebarProgress(data.progress_pct);
      showToast('✅ Đánh dấu hoàn thành!', 'success');
    } else {
      showToast(data.message || 'Có lỗi.', 'error');
      btn.textContent = '☑️ Đánh Dấu Hoàn Thành'; btn.disabled = false;
    }
  } catch {
    showToast('Lỗi kết nối.', 'error');
    btn.textContent = '☑️ Đánh Dấu Hoàn Thành'; btn.disabled = false;
  }
}

function updateSidebarProgress(pct) {
  if (pct === undefined) return;
  const bar = document.getElementById('sidebar-bar');
  const lbl = document.getElementById('sidebar-pct');
  if (bar) bar.style.width = pct + '%';
  if (lbl) lbl.textContent = pct + '%';
}

function finishCourse() {
  showToast('🎉 Chúc mừng bạn đã hoàn thành khóa học!', 'success');
  setTimeout(() => window.location.href = '/tai-khoan#courses', 2000);
}

function showNoVideoToast() {
  showToast('Bài học này chỉ có tài liệu đọc.', 'success');
}