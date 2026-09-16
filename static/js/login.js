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

// Single field validation rule for Login
function validateLoginField(fieldId) {
    const input = document.getElementById(fieldId);
    const error = document.getElementById(`${fieldId}Error`);
    let isValid = true;

    if (fieldId === 'email') {
        isValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value.trim());
    } else if (fieldId === 'password') {
        isValid = input.value.trim().length > 0;
    }

    if (!isValid) {
        error?.classList.remove('hidden');
    } else {
        error?.classList.add('hidden');
    }

    return isValid;
}

// Validate Forgot Password email input
function validateResetField() {
    const input = document.getElementById('resetEmail');
    const error = document.getElementById('resetEmailError');
    const isValid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(input.value.trim());

    if (!isValid) {
        error?.classList.remove('hidden');
    } else {
        error?.classList.add('hidden');
    }

    return isValid;
}

// Switch view to Forgot Password
function showForgotPassword() {
    document.getElementById('loginCard').classList.add('hidden');
    document.getElementById('loginAlert').classList.add('hidden');
    document.getElementById('forgotPasswordCard').classList.remove('hidden');
    document.getElementById('resetEmail').focus();
}

// Switch view back to Sign In
function showLoginCard() {
    document.getElementById('forgotPasswordCard').classList.add('hidden');
    document.getElementById('loginCard').classList.remove('hidden');
    document.getElementById('email').focus();
}

// Handle Login Submit
function handleLoginSubmit(e) {
    e.preventDefault();

    const isEmailValid = validateLoginField('email');
    const isPassValid = validateLoginField('password');
    const loginAlert = document.getElementById('loginAlert');

    if (isEmailValid && isPassValid) {
        const btn = document.getElementById('loginBtn');
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin text-xs"></i> <span>Authenticating...</span>`;
        loginAlert.classList.add('hidden');

        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = `<span>Sign In</span> <i class="fa-solid fa-arrow-right text-xs"></i>`;

            // Transition to Success Card
            document.getElementById('loginCard').classList.add('hidden');
            document.getElementById('successTitle').textContent = 'Welcome back!';
            document.getElementById('successDesc').textContent = 'You have successfully signed in. Redirecting to your dashboard...';
            document.getElementById('successCard').classList.remove('hidden');
        }, 1000);
    }
}

// Handle Forgot Password Submit
function handleForgotSubmit(e) {
    e.preventDefault();

    const isResetValid = validateResetField();

    if (isResetValid) {
        const btn = document.getElementById('resetBtn');
        btn.disabled = true;
        btn.innerHTML = `<i class="fa-solid fa-spinner animate-spin text-xs"></i> <span>Sending Link...</span>`;

        setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = `<span>Send Reset Link</span> <i class="fa-solid fa-paper-plane text-xs"></i>`;

            const resetEmailVal = document.getElementById('resetEmail').value.trim();

            // Transition to Success Card
            document.getElementById('forgotPasswordCard').classList.add('hidden');
            document.getElementById('successTitle').textContent = 'Reset link sent!';
            document.getElementById('successDesc').textContent = `We sent a password reset link to ${resetEmailVal}. Please check your inbox.`;
            document.getElementById('successCard').classList.remove('hidden');
        }, 1000);
    }
}

// Reset Login State
function resetLoginAll() {
    document.getElementById('loginForm').reset();
    document.getElementById('forgotForm').reset();
    document.getElementById('successCard').classList.add('hidden');
    document.getElementById('forgotPasswordCard').classList.add('hidden');
    document.getElementById('loginCard').classList.remove('hidden');
    document.getElementById('loginAlert').classList.add('hidden');

    const emailErr = document.getElementById('emailError');
    const passErr = document.getElementById('passwordError');
    const resetErr = document.getElementById('resetEmailError');

    if (emailErr) emailErr.classList.add('hidden');
    if (passErr) passErr.classList.add('hidden');
    if (resetErr) resetErr.classList.add('hidden');
}