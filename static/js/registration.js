// --- 1. Form Submission (Connected to Flask API) ---
async function handleRegister(event) {
  event.preventDefault();

  const fullname = document.getElementById('fullname').value.trim();
  const email = document.getElementById('email').value.trim();
  const password = document.getElementById('password').value;
  const confirmPassword = document.getElementById('confirm-password').value;
  const passwordError = document.getElementById('password-match-error');
  const btnSubmit = document.getElementById('btn-submit');

  if (password !== confirmPassword) {
    passwordError.textContent = 'Passwords do not match.';
    passwordError.style.display = 'block';
    document.getElementById('confirm-password').focus();
    return;
  }

  if (password.length < 8) {
    passwordError.textContent = 'Password must be at least 8 characters long.';
    passwordError.style.display = 'block';
    return;
  }

  passwordError.style.display = 'none';

  if (btnSubmit) {
    btnSubmit.disabled = true;
    btnSubmit.innerText = 'Creating Account...';
  }

  try {
    const res = await fetch('/auth/register', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        fullname: fullname,
        email: email,
        password: password,
        confirm_password: confirmPassword
      })
    });

    const data = await res.json();

    if (res.ok && data.success) {
      // Show success screen and navigate to login
      document.getElementById('form-content').style.display = 'none';
      document.getElementById('success-screen').style.display = 'block';

      setTimeout(() => {
        window.location.href = '/login';
      }, 1500);
    } else {
      passwordError.textContent = data.message || 'Registration failed.';
      passwordError.style.display = 'block';
    }
  } catch (err) {
    passwordError.textContent = 'Network error. Could not connect to authentication server.';
    passwordError.style.display = 'block';
  } finally {
    if (btnSubmit) {
      btnSubmit.disabled = false;
      btnSubmit.innerText = 'Create Account';
    }
  }
}

// --- 2. Background Canvas Particle Grid ---
(function initCanvas() {
  const canvas = document.getElementById('bg-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');

  let width, height;
  let particles = [];

  function resize() {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
  }

  window.addEventListener('resize', resize);
  resize();

  class NodeParticle {
    constructor() {
      this.x = Math.random() * width;
      this.y = Math.random() * height;
      this.vx = (Math.random() - 0.5) * 0.6;
      this.vy = (Math.random() - 0.5) * 0.6;
      this.radius = Math.random() * 2 + 1.5;
    }

    update() {
      this.x += this.vx;
      this.y += this.vy;

      if (this.x < 0 || this.x > width) this.vx *= -1;
      if (this.y < 0 || this.y > height) this.vy *= -1;
    }

    draw() {
      ctx.beginPath();
      ctx.arc(this.x, this.y, this.radius, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.fill();
    }
  }

  const count = Math.floor((width * height) / 18000);
  for (let i = 0; i < count; i++) {
    particles.push(new NodeParticle());
  }

  function animate() {
    ctx.clearRect(0, 0, width, height);

    for (let i = 0; i < particles.length; i++) {
      particles[i].update();
      particles[i].draw();

      for (let j = i + 1; j < particles.length; j++) {
        const dx = particles[i].x - particles[j].x;
        const dy = particles[i].y - particles[j].y;
        const dist = Math.hypot(dx, dy);

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
    requestAnimationFrame(animate);
  }

  animate();
})();