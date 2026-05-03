/* ═══════════════════════════════════════════════════════════
   FaceAttend — main.js
   Horloge temps réel, polling présences, utils UI
═══════════════════════════════════════════════════════════ */

// ── Horloge ────────────────────────────────────────────────
(function clock() {
  const el = document.getElementById('clock');
  if (!el) return;
  const tick = () => {
    const now  = new Date();
    const pad  = n => String(n).padStart(2, '0');
    el.textContent = `${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`;
  };
  tick();
  setInterval(tick, 1000);
})();

// ── Auto-dismiss alerts ────────────────────────────────────
document.querySelectorAll('.alert').forEach(alert => {
  setTimeout(() => {
    alert.style.transition = 'opacity .4s, transform .4s';
    alert.style.opacity = '0';
    alert.style.transform = 'translateX(20px)';
    setTimeout(() => alert.remove(), 400);
  }, 5000);
});

// ── Live session polling ───────────────────────────────────
window.startLivePolling = function(sessionId, intervalMs = 3000) {
  const updateStats = async () => {
    try {
      const res  = await fetch(`/api/attendance/session/${sessionId}/live`);
      const data = await res.json();

      // Update counters
      ['present', 'absent', 'total'].forEach(key => {
        const el = document.getElementById(`stat-${key}`);
        if (el && data[key] !== undefined) el.textContent = data[key];
      });

      // Update progress bar
      const bar = document.getElementById('presence-bar');
      if (bar && data.total > 0) {
        const pct = Math.round(data.present / data.total * 100);
        bar.style.width = pct + '%';
        document.getElementById('presence-pct').textContent = pct + '%';
      }

      // Update individual rows
      if (data.attendances) {
        data.attendances.forEach(att => {
          const row = document.querySelector(`[data-student="${att.student_id}"]`);
          if (row) {
            const badge = row.querySelector('.status-badge');
            if (badge) {
              badge.className = `badge badge--${att.status} status-badge`;
              badge.textContent = att.status;
            }
            const time = row.querySelector('.detect-time');
            if (time && att.detected_at) {
              const t = new Date(att.detected_at);
              time.textContent = `${String(t.getHours()).padStart(2,'0')}:${String(t.getMinutes()).padStart(2,'0')}`;
            }
            const conf = row.querySelector('.confidence');
            if (conf && att.confidence) {
              conf.textContent = Math.round(att.confidence * 100) + '%';
            }
          }
        });
      }
    } catch (e) {
      console.warn('[FaceAttend] Polling error:', e);
    }
  };

  updateStats();
  return setInterval(updateStats, intervalMs);
};

// ── Manual mark (quick action) ────────────────────────────
window.markAttendance = async function(sessionId, studentId, status) {
  const res = await fetch(`/api/attendance/session/${sessionId}/mark`, {
    method:  'POST',
    headers: { 'Content-Type': 'application/json' },
    body:    JSON.stringify({ student_id: studentId, status }),
  });
  const data = await res.json();
  if (data.success) {
    const row  = document.querySelector(`[data-student="${studentId}"]`);
    const badge = row?.querySelector('.status-badge');
    if (badge) { badge.className = `badge badge--${data.status} status-badge`; badge.textContent = data.status; }
  }
  return data;
};

// ── Chart.js helpers ───────────────────────────────────────
window.renderAttendanceChart = function(canvasId, labels, data, label = 'Taux de présence (%)') {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === 'undefined') return;

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [{
        label,
        data,
        backgroundColor: data.map(v =>
          v >= 80 ? 'rgba(0,245,160,.6)'
          : v >= 60 ? 'rgba(255,179,71,.6)'
          : 'rgba(255,77,109,.6)'
        ),
        borderRadius: 6,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw + '%' } },
      },
      scales: {
        x: { grid: { color: 'rgba(255,255,255,.04)' }, ticks: { color: '#8ba3c0' } },
        y: {
          min: 0, max: 100,
          grid: { color: 'rgba(255,255,255,.04)' },
          ticks: { color: '#8ba3c0', callback: v => v + '%' },
        },
      },
    },
  });
};

// ── Confirm dialog ─────────────────────────────────────────
window.confirm2 = function(msg) {
  // Simple inline confirm with styling (no native dialog)
  return window.confirm(msg);
};

// ── Toast ──────────────────────────────────────────────────
window.toast = function(message, type = 'info') {
  const map = { success: 'check-circle', danger: 'exclamation-circle', info: 'info-circle', warning: 'triangle-exclamation' };
  const div = document.createElement('div');
  div.className = `alert alert--${type}`;
  div.style.cssText = 'position:fixed;top:16px;right:20px;z-index:9999;max-width:360px;animation:fadeInUp .3s ease;';
  div.innerHTML = `<i class="fas fa-${map[type]||'info-circle'}"></i>${message}`;
  document.body.appendChild(div);
  setTimeout(() => { div.style.opacity='0'; div.style.transition='opacity .3s'; setTimeout(()=>div.remove(),300); }, 3500);
};

console.log('%cFaceAttend 🔍', 'color:#00f5a0;font-family:monospace;font-size:14px;font-weight:bold');
