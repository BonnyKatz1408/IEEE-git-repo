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
const ctx = canvas.getContext('2d');
let particles = [];

function resizeCanvas() {
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
  particles = [];
  const count = Math.floor((canvas.width * canvas.height) / 12000);
  for (let i = 0; i < count; i++) {
    particles.push(new Particle());
  }
}

function animateCanvas() {
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

// --- 3. Form Handling & Logic ---
const step1 = document.getElementById('step1');
const step2 = document.getElementById('step2');
const stepSuccess = document.getElementById('stepSuccess');

const btnStep1 = document.getElementById('btnStep1');
const btnBack = document.getElementById('btnBack');
const loginForm = document.getElementById('loginForm');
const alertBox = document.getElementById('alertBox');

const stepBadge1 = document.getElementById('stepBadge1');
const stepBadge2 = document.getElementById('stepBadge2');

const togglePassword = document.getElementById('togglePassword');
const passwordInput = document.getElementById('password');
const otpInputs = document.querySelectorAll('.otp-input');

function showAlert(msg) {
  alertBox.textContent = msg;
  alertBox.className = 'alert-box error';
}

function clearAlert() {
  alertBox.textContent = '';
  alertBox.className = 'alert-box';
}

// Password Reveal Toggle
togglePassword.addEventListener('click', () => {
  const type = passwordInput.getAttribute('type') === 'password' ? 'text' : 'password';
  passwordInput.setAttribute('type', type);
});

// Step 1 -> Step 2 Navigation
btnStep1.addEventListener('click', () => {
  clearAlert();
  const username = document.getElementById('username').value.trim();
  const password = passwordInput.value;

  if (!username || !password) {
    showAlert('Please fill in all required fields.');
    return;
  }

  // Smooth transition to Step 2
  step1.classList.remove('active');
  setTimeout(() => {
    step2.classList.add('active');
    stepBadge1.classList.remove('active');
    stepBadge1.classList.add('completed');
    stepBadge2.classList.add('active');
    otpInputs[0].focus();
  }, 200);
});

// Step 2 -> Step 1 Navigation
btnBack.addEventListener('click', () => {
  clearAlert();
  step2.classList.remove('active');
  setTimeout(() => {
    step1.classList.add('active');
    stepBadge2.classList.remove('active');
    stepBadge1.classList.remove('completed');
    stepBadge1.classList.add('active');
  }, 200);
});

// OTP Input Navigation Helpers
otpInputs.forEach((input, index) => {
  input.addEventListener('input', (e) => {
    if (e.target.value.length === 1 && index < otpInputs.length - 1) {
      otpInputs[index + 1].focus();
    }
  });

  input.addEventListener('keydown', (e) => {
    if (e.key === 'Backspace' && !e.target.value && index > 0) {
      otpInputs[index - 1].focus();
    }
  });

  input.addEventListener('paste', (e) => {
    e.preventDefault();
    const data = e.clipboardData.getData('text').trim();
    if (/^\d{6}$/.test(data)) {
      data.split('').forEach((char, i) => {
        if (otpInputs[i]) otpInputs[i].value = char;
      });
      otpInputs[5].focus();
    }
  });
});

// Form Submission (Final Verification)
loginForm.addEventListener('submit', (e) => {
  e.preventDefault();
  clearAlert();

  let code = '';
  otpInputs.forEach(i => code += i.value);

  if (code.length < 6) {
    showAlert('Please enter the complete 6-digit security code.');
    return;
  }

  // Complete Authentication
  step2.classList.remove('active');
  setTimeout(() => {
    stepSuccess.classList.add('active');
    stepBadge2.classList.remove('active');
    stepBadge2.classList.add('completed');
  }, 200);
});

// Reset Demo
document.getElementById('btnReset')?.addEventListener('click', () => {
  loginForm.reset();
  clearAlert();
  stepSuccess.classList.remove('active');
  step1.classList.add('active');
  stepBadge1.className = 'step-badge active';
  stepBadge2.className = 'step-badge';
});

// Resend Code Trigger
document.getElementById('btnResend').addEventListener('click', () => {
  alert('A new 6-digit verification code has been dispatched.');
});

// Initialize canvas and nodes on load
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