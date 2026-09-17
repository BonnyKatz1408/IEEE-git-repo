const architecturalModules = [
  { id: "api_gateway", name: "src/server.ts", kind: "entry", x: 8, y: 15, mx: 6, my: 10, incoming: 0, outgoing: 5, showOnMobile: true },
  { id: "auth_middleware", name: "middleware/auth.ts", kind: "middleware", x: 28, y: 14, mx: 60, my: 12, incoming: 1, outgoing: 3, showOnMobile: true },
  { id: "router_v1", name: "routes/v1/users.ts", kind: "controller", x: 28, y: 40, mx: 8, my: 76, incoming: 2, outgoing: 4, showOnMobile: true },
  { id: "payments_route", name: "routes/v1/billing.ts", kind: "controller", x: 22, y: 68, mx: 12, my: 45, incoming: 1, outgoing: 4, showOnMobile: false },
  { id: "user_service", name: "services/user.service.ts", kind: "service", x: 55, y: 22, mx: 56, my: 80, incoming: 3, outgoing: 2, showOnMobile: true },
  { id: "stripe_client", name: "lib/stripe/client.ts", kind: "external", x: 52, y: 74, mx: 54, my: 62, incoming: 2, outgoing: 1, showOnMobile: false },
  { id: "cache_store", name: "lib/cache/redis.ts", kind: "storage", x: 76, y: 16, mx: 64, my: 26, incoming: 2, outgoing: 0, showOnMobile: false },
  { id: "db_orm", name: "models/schema.prisma", kind: "storage", x: 77, y: 50, mx: 55, my: 78, incoming: 4, outgoing: 1, showOnMobile: true },
  { id: "event_bus", name: "workers/queue.ts", kind: "service", x: 72, y: 82, mx: 40, my: 88, incoming: 3, outgoing: 2, showOnMobile: false },
  { id: "metrics_telemetry", name: "utils/telemetry.ts", kind: "telemetry", x: 89, y: 32, mx: 78, my: 42, incoming: 5, outgoing: 0, showOnMobile: false },
  { id: "webhook_handler", name: "routes/webhooks.ts", kind: "controller", x: 10, y: 84, mx: 4, my: 86, incoming: 1, outgoing: 2, showOnMobile: false }
];

const moduleLinks = [
  { from: "api_gateway", to: "auth_middleware" },
  { from: "api_gateway", to: "router_v1" },
  { from: "api_gateway", to: "payments_route" },
  { from: "api_gateway", to: "webhook_handler" },
  { from: "auth_middleware", to: "user_service" },
  { from: "router_v1", to: "user_service" },
  { from: "payments_route", to: "stripe_client" },
  { from: "payments_route", to: "event_bus" },
  { from: "user_service", to: "cache_store" },
  { from: "user_service", to: "db_orm" },
  { from: "stripe_client", to: "db_orm" },
  { from: "event_bus", to: "db_orm" },
  { from: "webhook_handler", to: "event_bus" },
  { from: "db_orm", to: "metrics_telemetry" },
  { from: "cache_store", to: "metrics_telemetry" }
];

const canvas = document.getElementById('graphCanvas');
const ctx = canvas.getContext('2d');
const nodesOverlay = document.getElementById('nodesOverlay');
let width = 0;
let height = 0;
let highlightMode = false;
let isMobile = false;

function resize() {
  const dpr = window.devicePixelRatio || 1;
  width = window.innerWidth;
  height = window.innerHeight;

  canvas.width = width * dpr;
  canvas.height = height * dpr;
  ctx.resetTransform?.();
  ctx.scale(dpr, dpr);

  isMobile = width < 768;
  renderNodes();
}

function getNodeKindStyles(kind) {
  switch(kind) {
    case 'entry':
      return { tag: 'ENTRY', dotClass: 'dot-emerald' };
    case 'controller':
      return { tag: 'ROUTE', dotClass: 'dot-neutral' };
    case 'service':
      return { tag: 'SERVICE', dotClass: 'dot-emerald' };
    case 'storage':
      return { tag: 'STORAGE', dotClass: 'dot-amber' };
    case 'external':
      return { tag: 'CLIENT', dotClass: 'dot-neutral' };
    default:
      return { tag: 'MODULE', dotClass: 'dot-neutral' };
  }
}

function getActiveModules() {
  return isMobile ? architecturalModules.filter(m => m.showOnMobile) : architecturalModules;
}

function renderNodes() {
  nodesOverlay.innerHTML = '';
  const visibleModules = getActiveModules();

  visibleModules.forEach(mod => {
    const style = getNodeKindStyles(mod.kind);
    const card = document.createElement('div');
    const cardId = `node-${mod.id}`;
    card.id = cardId;
    
    card.className = `graph-node ${isMobile ? 'mobile-node' : 'desktop-node'}`;
    
    const xPct = isMobile ? mod.mx : mod.x;
    const yPct = isMobile ? mod.my : mod.y;
    
    card.style.left = `${(xPct / 100) * width}px`;
    card.style.top = `${(yPct / 100) * height}px`;

    if (isMobile) {
      card.innerHTML = `
        <div class="node-row">
          <div class="node-title-group">
            <span class="node-dot ${style.dotClass}"></span>
            <span class="node-name">${mod.name.split('/').pop()}</span>
          </div>
          <span class="node-tag">${style.tag}</span>
        </div>
      `;
    } else {
      card.innerHTML = `
        <div class="node-row">
          <div class="node-title-group">
            <span class="node-dot ${style.dotClass}"></span>
            <span class="node-name">${mod.name}</span>
          </div>
          <span class="node-tag">${style.tag}</span>
        </div>
        <div class="node-io">
          <span>in: ${mod.incoming}</span>
          <span>out: ${mod.outgoing}</span>
        </div>
      `;
    }

    const activate = () => {
      highlightMode = mod.id;
      document.querySelectorAll('.graph-node').forEach(el => el.classList.remove('is-active'));
      card.classList.add('is-active');
    };

    const deactivate = () => {
      if (!isMobile) {
        highlightMode = false;
        card.classList.remove('is-active');
      }
    };

    card.addEventListener('mouseenter', activate);
    card.addEventListener('mouseleave', deactivate);
    card.addEventListener('click', (e) => {
      e.stopPropagation();
      activate();
    });

    nodesOverlay.appendChild(card);
  });
}

document.addEventListener('click', (e) => {
  if (!e.target.closest('.graph-node')) {
    highlightMode = false;
    document.querySelectorAll('.graph-node').forEach(el => el.classList.remove('is-active'));
  }
});

function drawGraph() {
  ctx.clearRect(0, 0, width, height);
  const visibleModules = getActiveModules();
  const visibleIds = new Set(visibleModules.map(m => m.id));

  moduleLinks.forEach((link) => {
    if (!visibleIds.has(link.from) || !visibleIds.has(link.to)) return;

    const source = visibleModules.find(m => m.id === link.from);
    const target = visibleModules.find(m => m.id === link.to);
    if (!source || !target) return;

    const sourceEl = document.getElementById(`node-${source.id}`);
    const targetEl = document.getElementById(`node-${target.id}`);

    let sx, sy, tx, ty;
    if (sourceEl && targetEl) {
      const sRect = sourceEl.getBoundingClientRect();
      const tRect = targetEl.getBoundingClientRect();
      sx = sRect.left + sRect.width / 2;
      sy = sRect.top + sRect.height / 2;
      tx = tRect.left + tRect.width / 2;
      ty = tRect.top + tRect.height / 2;
    } else {
      const sxPct = isMobile ? source.mx : source.x;
      const syPct = isMobile ? source.my : source.y;
      const txPct = isMobile ? target.mx : target.x;
      const tyPct = isMobile ? target.my : target.y;
      sx = (sxPct / 100) * width + 50;
      sy = (syPct / 100) * height + 18;
      tx = (txPct / 100) * width + 50;
      ty = (tyPct / 100) * height + 18;
    }

    const isHighlighted = highlightMode && (source.id === highlightMode || target.id === highlightMode);

    ctx.beginPath();
    const midX = (sx + tx) / 2;
    ctx.moveTo(sx, sy);
    ctx.bezierCurveTo(midX, sy, midX, ty, tx, ty);

    if (isHighlighted) {
      ctx.strokeStyle = 'rgba(52, 211, 153, 0.95)';
      ctx.lineWidth = isMobile ? 1.8 : 2.2;
      ctx.setLineDash([5, 3]);
    } else {
      ctx.strokeStyle = isMobile ? 'rgba(255, 255, 255, 0.16)' : 'rgba(255, 255, 255, 0.22)';
      ctx.lineWidth = isMobile ? 1.0 : 1.2;
      ctx.setLineDash([4, 4]);
    }
    ctx.stroke();

    const t = 0.5;
    const cx = (1 - t) * (1 - t) * (1 - t) * sx + 3 * (1 - t) * (1 - t) * t * midX + 3 * (1 - t) * t * t * midX + t * t * t * tx;
    const cy = (1 - t) * (1 - t) * (1 - t) * sy + 3 * (1 - t) * (1 - t) * t * sy + 3 * (1 - t) * t * t * ty + t * t * t * ty;

    ctx.beginPath();
    ctx.arc(cx, cy, isHighlighted ? (isMobile ? 2.5 : 3.5) : (isMobile ? 1.5 : 2), 0, Math.PI * 2);
    ctx.fillStyle = isHighlighted ? '#34d399' : 'rgba(255, 255, 255, 0.45)';
    ctx.fill();
  });

  requestAnimationFrame(drawGraph);
}

window.addEventListener('DOMContentLoaded', () => {
  resize();
  requestAnimationFrame(drawGraph);
});
window.addEventListener('resize', resize);
window.addEventListener('orientationchange', () => {
  setTimeout(resize, 150);
});