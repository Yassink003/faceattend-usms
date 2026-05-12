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

// ── Chart.js — thème FaceAttend (présences / absences) ─────
const CHART_FONT = { family: "'Inter', system-ui, sans-serif", size: 11 };
const CHART_ANIM = { duration: 1000, easing: 'easeOutQuart' };

/** Barres horizontales empilées : présents / retards / absents / justifiés par cours */
window.renderCourseStackedChart = function (canvasId, courses) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === 'undefined') return null;
  if (!courses || !courses.length) return null;

  const labels = courses.map(c => c.course);
  const parent = canvas.parentElement;
  if (parent) {
    parent.classList.add('chart-panel__body--stacked');
    const h = Math.min(620, Math.max(300, labels.length * 52 + 150));
    parent.style.height = h + 'px';
    parent.style.minHeight = h + 'px';
  }

  return new Chart(canvas, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Présents',
          data: courses.map(c => c.present || 0),
          backgroundColor: 'rgba(13, 148, 136, 0.88)',
          borderRadius: { topRight: 6, bottomRight: 6 },
          borderSkipped: false,
        },
        {
          label: 'Retards',
          data: courses.map(c => c.late || 0),
          backgroundColor: 'rgba(234, 179, 8, 0.9)',
          borderRadius: 4,
          borderSkipped: false,
        },
        {
          label: 'Absents',
          data: courses.map(c => c.absent || 0),
          backgroundColor: 'rgba(220, 38, 38, 0.88)',
          borderRadius: 4,
          borderSkipped: false,
        },
        {
          label: 'Justifiés',
          data: courses.map(c => c.excused || 0),
          backgroundColor: 'rgba(79, 70, 229, 0.78)',
          borderRadius: { topRight: 8, bottomRight: 8 },
          borderSkipped: false,
        },
      ],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      animation: CHART_ANIM,
      layout: { padding: { left: 4, right: 12, top: 8, bottom: 4 } },
      interaction: { mode: 'index', axis: 'y', intersect: false },
      plugins: {
        legend: {
          position: 'bottom',
          align: 'center',
          labels: {
            usePointStyle: true,
            pointStyle: 'rectRounded',
            padding: 12,
            boxWidth: 10,
            boxHeight: 10,
            font: CHART_FONT,
            color: '#475569',
          },
        },
        tooltip: {
          callbacks: {
            footer: (items) => {
              const sum = items.reduce((a, i) => a + (Number(i.raw) || 0), 0);
              return sum ? `Total saisies : ${sum}` : '';
            },
          },
        },
      },
      scales: {
        x: {
          stacked: true,
          grid: { color: 'rgba(15, 23, 42, 0.06)' },
          ticks: { color: '#64748b', font: CHART_FONT },
          border: { display: false },
        },
        y: {
          stacked: true,
          grid: { display: false },
          ticks: {
            color: '#334155',
            font: { ...CHART_FONT, weight: '600', size: 11 },
            autoSkip: false,
            maxRotation: 0,
            padding: 10,
            callback(value) {
              const s = String(value == null ? '' : value);
              return s.length > 16 ? s.slice(0, 14) + '…' : s;
            },
          },
          border: { display: false },
        },
      },
    },
  });
};

/** Courbe de tendance des absences (par date de séance) */
window.renderAbsenceTrendChart = function (canvasId, labels, counts) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === 'undefined') return null;

  const chart = new Chart(canvas, {
    type: 'line',
    data: {
      labels: labels || [],
      datasets: [{
        label: 'Absences enregistrées',
        data: counts || [],
        borderColor: 'rgba(220, 38, 38, 0.95)',
        borderWidth: 2.5,
        tension: 0.38,
        fill: true,
        backgroundColor(context) {
          const { chart } = context;
          const { ctx, chartArea } = chart;
          if (!chartArea) return 'rgba(220, 38, 38, 0.08)';
          const g = ctx.createLinearGradient(0, chartArea.bottom, 0, chartArea.top);
          g.addColorStop(0, 'rgba(220, 38, 38, 0.04)');
          g.addColorStop(0.5, 'rgba(220, 38, 38, 0.12)');
          g.addColorStop(1, 'rgba(79, 70, 229, 0.18)');
          return g;
        },
        pointBackgroundColor: '#fff',
        pointBorderColor: 'rgba(220, 38, 38, 1)',
        pointBorderWidth: 2,
        pointRadius: 4,
        pointHoverRadius: 8,
        pointHoverBackgroundColor: 'rgba(79, 70, 229, 1)',
        pointHoverBorderColor: '#fff',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      animation: CHART_ANIM,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => ` ${ctx.parsed.y} absence(s)`,
          },
        },
      },
      scales: {
        x: {
          grid: { display: false },
          ticks: { color: '#64748b', maxRotation: 45, font: CHART_FONT },
          border: { display: false },
        },
        y: {
          beginAtZero: true,
          suggestedMax: Math.max(5, Math.max(0, ...((counts && counts.length) ? counts : [0])) + 2),
          grid: { color: 'rgba(15, 23, 42, 0.05)' },
          ticks: { stepSize: 1, color: '#64748b', font: CHART_FONT },
          border: { display: false },
        },
      },
    },
  });

  return chart;
};

/** Vue globale des statuts — polar area (effet « radar » soft) */
window.renderStatusPolarChart = function (canvasId, mix) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === 'undefined') return null;
  const values = [
    mix.present || 0,
    mix.late || 0,
    mix.absent || 0,
    mix.excused || 0,
  ];
  const total = values.reduce((a, b) => a + b, 0);
  if (total === 0) return null;

  const parent = canvas.parentElement;
  if (parent) {
    parent.classList.add('chart-panel__body--polar');
    parent.style.height = '340px';
    parent.style.minHeight = '340px';
  }

  return new Chart(canvas, {
    type: 'polarArea',
    data: {
      labels: ['Présents', 'Retards', 'Absents', 'Justifiés'],
      datasets: [{
        data: values,
        backgroundColor: [
          'rgba(13, 148, 136, 0.75)',
          'rgba(234, 179, 8, 0.8)',
          'rgba(220, 38, 38, 0.78)',
          'rgba(79, 70, 229, 0.72)',
        ],
        borderWidth: 2,
        borderColor: '#ffffff',
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: CHART_ANIM,
      layout: { padding: { top: 10, bottom: 8, left: 8, right: 8 } },
      scales: {
        r: {
          grid: { color: 'rgba(15, 23, 42, 0.06)' },
          angleLines: { color: 'rgba(15, 23, 42, 0.05)' },
          /* Libellés uniquement dans la légende : évite doublon et superposition sur le disque */
          pointLabels: { display: false },
          ticks: { display: false, backdropColor: 'transparent' },
        },
      },
      plugins: {
        legend: {
          position: 'bottom',
          align: 'center',
          labels: {
            usePointStyle: true,
            pointStyle: 'circle',
            padding: 16,
            boxWidth: 8,
            boxHeight: 8,
            font: CHART_FONT,
            color: '#475569',
          },
        },
        tooltip: {
          callbacks: {
            label: (ctx) => {
              const v = ctx.raw;
              const pct = total ? ((v / total) * 100).toFixed(1) : 0;
              return ` ${v} (${pct}%)`;
            },
          },
        },
      },
    },
  });
};

/** Donut étudiant + texte central (séances) */
window.renderStudentPresenceDonut = function (canvasId, present, absent, excused) {
  const canvas = document.getElementById(canvasId);
  if (!canvas || typeof Chart === 'undefined') return null;
  const total = present + absent + excused;

  const centerText = {
    id: 'centerText',
    afterDraw(chart) {
      const { ctx, chartArea: { top, bottom, left, right } } = chart;
      const x = (left + right) / 2;
      const y = (top + bottom) / 2 + 4;
      ctx.save();
      ctx.font = "800 1.35rem 'Outfit', sans-serif";
      ctx.fillStyle = '#0c1222';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(`${total}`, x, y - 10);
      ctx.font = "600 0.68rem 'Inter', sans-serif";
      ctx.fillStyle = '#64748b';
      ctx.fillText('séances', x, y + 12);
      ctx.restore();
    },
  };

  return new Chart(canvas, {
    type: 'doughnut',
    plugins: [centerText],
    data: {
      labels: ['Présences', 'Absences', 'Justifiées'],
      datasets: [{
        data: [present, absent, excused],
        backgroundColor: [
          'rgba(13, 148, 136, 0.88)',
          'rgba(220, 38, 38, 0.85)',
          'rgba(79, 70, 229, 0.82)',
        ],
        borderColor: ['#fff', '#fff', '#fff'],
        borderWidth: 3,
        hoverOffset: 14,
        spacing: 2,
      }],
    },
    options: {
      responsive: true,
      cutout: '68%',
      animation: { animateRotate: true, animateScale: true, ...CHART_ANIM },
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#64748b', font: { size: 12 }, padding: 16, usePointStyle: true },
        },
      },
    },
  });
};

/** Ancien graphique barres verticales (% par cours) — conservé pour compat */
window.renderAttendanceChart = function (canvasId, labels, data, label = 'Taux de présence (%)') {
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
          v >= 80 ? 'rgba(79,70,229,.72)'
          : v >= 60 ? 'rgba(194,65,12,.65)'
          : 'rgba(220,38,38,.68)'
        ),
        borderRadius: 10,
        borderSkipped: false,
      }],
    },
    options: {
      responsive: true,
      animation: CHART_ANIM,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: ctx => ctx.raw + '%' } },
      },
      scales: {
        x: { grid: { color: 'rgba(15,23,42,.06)' }, ticks: { color: '#64748b' } },
        y: {
          min: 0, max: 100,
          grid: { color: 'rgba(15,23,42,.06)' },
          ticks: { color: '#64748b', callback: v => v + '%' },
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

console.log('%cFaceAttend 🔍', 'color:#4f46e5;font-family:monospace;font-size:14px;font-weight:bold');
