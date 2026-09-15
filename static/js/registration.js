let countdownInterval;
let timerSeconds = 60;

// Toggle Password Visibility
function toggleVisibility(inputId, iconId) {
    const input = document.getElementById(inputId);
    const icon = document.getElementById(iconId);

    if (input.type === 'password') {
        input.type = 'text';
        icon.className = 'fa-regular fa-eye-slash text-xs text-slate-200';
    } else {
        input.type = 'password';
        icon.className = 'fa-regular fa-eye text-xs text-slate-400';
    }
}

// Real-time Password Strength Meter
function evaluatePasswordStrength(val) {
    const label = document.getElementById('passwordStrengthText');
    const bars = [
        document.getElementById('pBar1'),
        document.getElementById('pBar2'),
        document.getElementById('pBar3'),
        document.getElementById('pBar4')
    ];

    bars.forEach(b => b.className = 'h-1 bg-slate-800 rounded-full transition-colors duration-200');

    if (!val) {
        label.textContent = 'Min 8 chars';
        label.className = 'text-[10px] text-slate-500';
        return;
    }

    let score = 0;
    if (val.length >= 8) score++;
    if (/[A-Z]/.test(val) && /[a-z]/.test(val)) score++;
    if (/[0-9]/.test(val)) score++;
    if (/[^A-Za-z0-9]/.test(val)) score++;

    const colors = ['bg-rose-500', 'bg-amber-500', 'bg-blue-400', 'bg-indigo-500'];
    const labels = ['Weak', 'Fair', 'Good', 'Strong'];
    const labelColors = ['text-rose-400', 'text-amber-400', 'text-blue-400', 'text-indigo-400'];

    for (let i = 0; i < score; i++) {
        bars[i].className = `h-1 ${colors[score - 1]} rounded-full transition-colors duration-200`;
    }

    label.textContent = labels[score - 1] || 'Weak';
    label.className = `text-[10px] ${labelColors[score - 1] || 'text-rose-400'}`;
}

// Single field validation rule
function validateField(fieldId) {
    const input = document.getElementById(fieldId);
    const error = document.getElementById(`${fieldId}Error`);
    let isValid = true;

    if (fieldId === 'fullName') {
        isValid = input.value.trim().length >= 2;
    } else if (fieldId === 'email') {
        isValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value.trim());
    } else if (fieldId === 'password') {
        isValid = input.value.length >= 8;
    } else if (fieldId === 'confirmPassword') {
        const pass = document.getElementById('password').value;
        isValid = input.value.length > 0 && input.value === pass;
    } else if (fieldId === 'terms') {
        isValid = input.checked;
    }

    if (!isValid) {
        error?.classList.remove('hidden');
    } else {
        error?.classList.add('hidden');
    }

    return isValid;
}

// Handle Step 1 Submit
function handleStep1Submit(e) {
    e.preventDefault();

    const isNameValid = validateField('fullName');
    const isEmailValid = validateField('email');
    const isPassValid = validateField('password');
    const isConfirmValid = validateField('confirmPassword');
    const isTermsValid = validateField('terms');

    if (isNameValid && isEmailValid && isPassValid && isConfirmValid && isTermsValid) {
        const btn = document.getElementById('step1Btn');
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin text-xs"></i> <span>Sending Code...</span>`;

        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = `<span>Continue to Verification</span> <i class="fa-solid fa-arrow-right text-xs"></i>`;

            // Transition to Step 2
            document.getElementById('step1Card').classList.add('hidden');
            document.getElementById('step2Card').classList.remove('hidden');
            document.getElementById('targetEmail').textContent = document.getElementById('email').value.trim();

            // Update Step Indicators
            document.getElementById('stepBadge1').className = 'flex items-center gap-2 text-xs font-medium px-3 py-1 rounded-full bg-slate-900/60 text-slate-500 border border-slate-800 transition-all';
            document.getElementById('stepBadge2').className = 'flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 transition-all';

            // Start Resend Timer and Focus First OTP Box
            startResendTimer();
            const otpInputs = document.querySelectorAll('.otp-input');
            if (otpInputs.length > 0) otpInputs[0].focus();
        }, 800);
    }
}

// Return to Step 1
function goToStep1() {
    document.getElementById('step2Card').classList.add('hidden');
    document.getElementById('step1Card').classList.remove('hidden');

    document.getElementById('stepBadge1').className = 'flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 transition-all';
    document.getElementById('stepBadge2').className = 'flex items-center gap-2 text-xs font-medium px-3 py-1 rounded-full bg-slate-900/60 text-slate-500 border border-slate-800 transition-all';

    clearInterval(countdownInterval);
}

// OTP Input Interactivity Logic
document.addEventListener('DOMContentLoaded', () => {
    const otpInputs = document.querySelectorAll('.otp-input');
    otpInputs.forEach((input, index) => {
        // Focus next on input
        input.addEventListener('input', (e) => {
            const val = e.target.value;
            if (val.length === 1 && index < otpInputs.length - 1) {
                otpInputs[index + 1].focus();
            }
        });

        // Backspace handling
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !input.value && index > 0) {
                otpInputs[index - 1].focus();
            }
        });

        // Paste handling
        input.addEventListener('paste', (e) => {
            e.preventDefault();
            const pastedData = e.clipboardData.getData('text').trim().replace(/[^0-9]/g, '');
            if (pastedData) {
                const chars = pastedData.split('');
                otpInputs.forEach((inp, idx) => {
                    if (chars[idx]) {
                        inp.value = chars[idx];
                    }
                });
                const targetIdx = Math.min(chars.length, otpInputs.length) - 1;
                if (targetIdx >= 0) otpInputs[targetIdx].focus();
            }
        });
    });
});

// Start Resend Timer
function startResendTimer() {
    clearInterval(countdownInterval);
    timerSeconds = 60;
    const timerText = document.getElementById('timerText');
    const resendBtn = document.getElementById('resendBtn');
    const countdownEl = document.getElementById('countdown');

    resendBtn.disabled = true;
    timerText.classList.remove('hidden');
    countdownEl.textContent = timerSeconds;

    countdownInterval = setInterval(() => {
        timerSeconds--;
        countdownEl.textContent = timerSeconds;
        if (timerSeconds <= 0) {
            clearInterval(countdownInterval);
            resendBtn.disabled = false;
            timerText.classList.add('hidden');
        }
    }, 1000);
}

function resendOtp() {
    const resendBtn = document.getElementById('resendBtn');
    resendBtn.innerText = 'Sending...';
    setTimeout(() => {
        resendBtn.innerText = 'Resend Code';
        startResendTimer();
    }, 600);
}

// Handle Step 2 OTP Verification Submit
function handleOtpSubmit(e) {
    e.preventDefault();
    const otpInputs = document.querySelectorAll('.otp-input');
    const otpCode = Array.from(otpInputs).map(inp => inp.value).join('');
    const otpError = document.getElementById('otpError');

    if (otpCode.length < 6) {
        otpError.classList.remove('hidden');
        return;
    }

    otpError.classList.add('hidden');
    const verifyBtn = document.getElementById('verifyBtn');
    verifyBtn.disabled = true;
    verifyBtn.innerHTML = `<i class="fa-solid fa-spinner animate-spin text-xs"></i> <span>Verifying...</span>`;

    setTimeout(() => {
        document.getElementById('step2Card').classList.add('hidden');
        document.getElementById('successCard').classList.remove('hidden');
    }, 1000);
}

// Reset Form
function resetAll() {
    document.getElementById('registrationForm').reset();
    const otpInputs = document.querySelectorAll('.otp-input');
    otpInputs.forEach(input => input.value = '');
    document.getElementById('successCard').classList.add('hidden');
    document.getElementById('step2Card').classList.add('hidden');
    document.getElementById('step1Card').classList.remove('hidden');

    document.getElementById('stepBadge1').className = 'flex items-center gap-2 text-xs font-semibold px-3 py-1 rounded-full bg-indigo-500/10 text-indigo-400 border border-indigo-500/20 transition-all';
    document.getElementById('stepBadge2').className = 'flex items-center gap-2 text-xs font-medium px-3 py-1 rounded-full bg-slate-900/60 text-slate-500 border border-slate-800 transition-all';

    const verifyBtn = document.getElementById('verifyBtn');
    verifyBtn.disabled = false;
    verifyBtn.innerHTML = `<span>Verify & Complete</span> <i class="fa-solid fa-check text-xs"></i>`;

    evaluatePasswordStrength('');
    clearInterval(countdownInterval);
}