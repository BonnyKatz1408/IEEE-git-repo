const canvas = document.getElementById('bg-canvas');
const ctx = canvas.getContext('2d');

let width = canvas.width = window.innerWidth;
let height = canvas.height = window.innerHeight;

window.addEventListener('resize', () => {
    width = canvas.width = window.innerWidth;
    height = canvas.height = window.innerHeight;
    initNodes();
});

// Graph Nodes logic with dimmed settings
const NODE_COUNT = 32;
let nodes = [];

class GraphNode {
    constructor() {
        this.x = Math.random() * width;
        this.y = Math.random() * height;
        this.vx = (Math.random() - 0.5) * 0.3;
        this.vy = (Math.random() - 0.5) * 0.3;
        this.radius = Math.random() * 2 + 1;
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
        ctx.fillStyle = 'rgba(255, 255, 255, 0.25)';
        ctx.fill();
    }
}

function initNodes() {
    nodes = [];
    for (let i = 0; i < NODE_COUNT; i++) {
        nodes.push(new GraphNode());
    }
}

function animateGraph() {
    ctx.clearRect(0, 0, width, height);

    // Draw subtle dimmed connecting lines
    for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
            const dx = nodes[i].x - nodes[j].x;
            const dy = nodes[i].y - nodes[j].y;
            const dist = Math.sqrt(dx * dx + dy * dy);

            if (dist < 180) {
                ctx.beginPath();
                ctx.moveTo(nodes[i].x, nodes[i].y);
                ctx.lineTo(nodes[j].x, nodes[j].y);
                const alpha = (1 - dist / 180) * 0.08;
                ctx.strokeStyle = `rgba(255, 255, 255, ${alpha})`;
                ctx.setLineDash([3, 3]);
                ctx.lineWidth = 1;
                ctx.stroke();
                ctx.setLineDash([]);
            }
        }
    }

    // Update & draw nodes
    nodes.forEach(node => {
        node.update();
        node.draw();
    });

    requestAnimationFrame(animateGraph);
}

initNodes();
animateGraph();

const sampleNodes = [
    { name: 'src/server.ts', tag: 'ENTRY', color: '#3b82f6', in: 0, out: 5, top: '18%', left: '12%' },
    { name: 'middleware/auth', tag: 'MODULE', color: '#8b5cf6', in: 1, out: 3, top: '22%', left: '30%' },
    { name: 'services/user', tag: 'SERVICE', color: '#10b981', in: 3, out: 2, top: '35%', left: '60%' },
    { name: 'lib/cache/redis', tag: 'STORAGE', color: '#f59e0b', in: 2, out: 0, top: '20%', left: '78%' },
    { name: 'routes/v1/users', tag: 'ROUTE', color: '#ec4899', in: 2, out: 4, top: '52%', left: '26%' },
    { name: 'models/schema', tag: 'STORAGE', color: '#f59e0b', in: 4, out: 1, top: '62%', left: '75%' },
    { name: 'utils/telemetry', tag: 'MODULE', color: '#8b5cf6', in: 5, out: 0, top: '48%', left: '86%' },
    { name: 'workers/queue', tag: 'SERVICE', color: '#10b981', in: 3, out: 2, top: '82%', left: '70%' }
];

const container = document.getElementById('node-overlay-container');
sampleNodes.forEach(item => {
    const el = document.createElement('div');
    el.className = 'dom-node';
    el.style.top = item.top;
    el.style.left = item.left;
    el.innerHTML = `
        <span class="dot" style="background: ${item.color};"></span>
        <span>${item.name}</span>
        <span class="tag">${item.tag}</span>
        <span class="metrics">in: ${item.in} out: ${item.out}</span>
    `;
    container.appendChild(el);
});

let currentStep = 1;

function goToStep(stepNumber) {
    const step1 = document.getElementById('step-1');
    const step2 = document.getElementById('step-2');
    const btnBack = document.getElementById('btn-back');
    const btnNext = document.getElementById('btn-next');
    const btnSubmit = document.getElementById('btn-submit');
    const progressBar = document.getElementById('progress-bar');
    const stepTitle = document.getElementById('step-title');
    const stepIndicator = document.getElementById('step-indicator');
    const passwordMatchError = document.getElementById('password-match-error');

    // Validate Step 1 before proceeding
    if (stepNumber === 2) {
        const fullname = document.getElementById('fullname');
        const email = document.getElementById('email');
        const password = document.getElementById('password');
        const confirmPassword = document.getElementById('confirm-password');

        passwordMatchError.style.display = 'none';

        if (!fullname.checkValidity() || !email.checkValidity() || !password.checkValidity() || !confirmPassword.checkValidity()) {
            fullname.reportValidity() || email.reportValidity() || password.reportValidity() || confirmPassword.reportValidity();
            return;
        }

        if (password.value !== confirmPassword.value) {
            passwordMatchError.style.display = 'block';
            confirmPassword.focus();
            return;
        }

        step1.classList.remove('active');
        step1.classList.add('exit-left');
        step2.classList.add('active');

        btnBack.style.display = 'inline-flex';
        btnNext.style.display = 'none';
        btnSubmit.style.display = 'inline-flex';

        progressBar.style.width = '100%';
        stepTitle.textContent = 'Preferences';
        stepIndicator.textContent = 'Step 2 of 2';
        currentStep = 2;
    } else {
        step2.classList.remove('active');
        step1.classList.remove('exit-left');
        step1.classList.add('active');

        btnBack.style.display = 'none';
        btnNext.style.display = 'inline-flex';
        btnSubmit.style.display = 'none';

        progressBar.style.width = '50%';
        stepTitle.textContent = 'Create Account';
        stepIndicator.textContent = 'Step 1 of 2';
        currentStep = 1;
    }
}

function handleRegister(e) {
    e.preventDefault();
    
    // Validate Step 2 inputs
    const role = document.getElementById('role');
    const language = document.getElementById('language');

    if (!role.checkValidity() || !language.checkValidity()) {
        role.reportValidity() || language.reportValidity();
        return;
    }

    // Hide form and display success feedback
    document.getElementById('form-content').style.display = 'none';
    document.getElementById('success-screen').style.display = 'block';
}