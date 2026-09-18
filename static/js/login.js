// --- 1. Background Nodes Data & Setup ---
const nodeData = [
  { label: 'auth/server.ts', tag: 'ENTRY', x: 12, y: 15 },
  { label: 'middleware/jwt.ts', tag: 'MODULE', x: 28, y: 30 },
  { label: 'services/identity...', tag: 'SERVICE', x: 62, y: 20 },
  { label: 'lib/crypto/rsa', tag: 'STORAGE', x: 78, y: 15 },
  { label: 'models/session', tag: 'STORAGE', x: 75, y: 65 },
  { label: 'routes/v1/auth...', tag: 'ROUTE', x: 22, y: 70 },
  { label: 'workers/mfa...', tag: 'SERVICE', x: 68, y: 82 },
  { label: 'utils/telemetry', tag: 'MODULE', x: 86, y: 48 }
];

function initNodes() {
  const container = document.getElementById('nodeContainer');
  if (!container) return;
  nodeData.forEach(node => {
    const el = document.createElement('div');
    el.className = 'node-box';
    el.style.left = `${node.x}%`;
    el.style.top = `${node.y}%`;
    el.innerHTML = `<span>${node.label}</span><span class="node-tag">${node.tag}</span>`;
    container.appendChild(el);
  });
}

// --- 2. Interactive Canvas Particle Mesh ---
const canvas = document.getElementById('bgCanvas');
const ctx = canvas ? canvas.getContext('2d') : null;
let particles = [];

function resizeCanvas() {
  if (!canvas) return;
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
}

class Particle {
  constructor() {
    this.x = Math.random() * canvas.width;
    this.y = Math.random() * canvas.height;
    this.vx = (Math.random() - 0.5) * 0.4;
    this.vy = (Math.random() - 0.5) * 0.4;
    this.radius = Math.random() * 1.5 + 1;
  }

  update() {
    this.x += this.vx;
    this.y += this.vy;

    if (this.x < 0 || this.x > canvas.width) this.vx *= -1;
    if (this.y < 0 || this.y > canvas.height) this.vy *= -1;
  }

  draw() {
    ctx.beginPath();
    ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.fill();
  }
}

function initParticles() {
  if (!canvas) return;
  particles = [];
  const count = Math.floor((canvas.width * canvas.height) / 12000);
  for (let i = 0; i < count; i++) {
    particles.push(new Particle());
  }
}

function animateCanvas() {
  if (!ctx) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  for (let i = 0; i < particles.length; i++) {
    particles[i].update();
    particles[i].draw();

    for (let j = i + 1; j < particles.length; j++) {
      const dx = particles[i].x - particles[j].x;
      const dy = particles[i].y - particles[j].y;
      const dist = Math.sqrt(dx * dx + dy * dy);

      if (dist < 130) {
        ctx.beginPath();
        ctx.moveTo(particles[i].x, particles[i].y);
        ctx.lineTo(particles[j].x, particles[j].y);
        ctx.strokeStyle = `rgba(255, 255, 255, ${0.12 * (1 - dist / 130)})`;
        ctx.lineWidth = 0.8;
        ctx.stroke();
      }
    }
  }
  requestAnimationFrame(animateCanvas);
}

// --- 3. Form Handling & Authentication ---
const step1 = document.getElementById('step1');
const stepSuccess = document.getElementById('stepSuccess');
const loginForm = document.getElementById('loginForm');
const alertBox = document.getElementById('alertBox');
const togglePassword = document.getElementById('togglePassword');
const passwordInput = document.getElementById('password');
const btnSubmit = document.getElementById('btnSubmit');

function showAlert(msg) {
  if (!alertBox) return;
  alertBox.textContent = msg;
  alertBox.className = 'alert-box error';
  alertBox.style.display = 'block';
}

function clearAlert() {
  if (!alertBox) return;
  alertBox.textContent = '';
  alertBox.className = 'alert-box';
  alertBox.style.display = 'none';
}

// Password Reveal Toggle
togglePassword?.addEventListener('click', () => {
  const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
  passwordInput.setAttribute('type', type);
});

// Form Submission (Connected to Flask API)
loginForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  clearAlert();

  const email = document.getElementById('username').value.trim();
  const password = passwordInput.value;
  const remember = document.getElementById('rememberMe')?.checked || false;

  if (!email || !password) {
    showAlert('Please fill in all required fields.');
    return;
  }

  // Disable button while processing
  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.style.opacity = '0.7';
  }

  try {
    const res = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password, remember })
    });

    const data = await res.json();

    if (res.ok && data.success) {
      step1.classList.remove('active');
      setTimeout(() => {
        stepSuccess.classList.add('active');
      }, 200);

      // Redirect to the dashboard after brief animation
      setTimeout(() => {
        window.location.href = data.redirect || '/analyze';
      }, 1200);
    } else {
      showAlert(data.message || 'Authentication failed. Please check your credentials.');
    }
  } catch (err) {
    showAlert('Network error. Failed to reach authentication node.');
  } finally {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.style.opacity = '1';
    }
  }
});

// Reset Demo State
document.getElementById('btnReset')?.addEventListener('click', () => {
  loginForm.reset();
  clearAlert();
  stepSuccess.classList.remove('active');
  step1.classList.add('active');
});

// Window Listeners
window.addEventListener('resize', () => {
  resizeCanvas();
  initParticles();
});

window.addEventListener('DOMContentLoaded', () => {
  initNodes();
  resizeCanvas();
  initParticles();
  animateCanvas();
});