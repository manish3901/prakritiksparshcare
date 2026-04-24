// main.js - Base scripts for Praktutik SparshCare
document.addEventListener('DOMContentLoaded', () => {
    console.log('Prakrutik SparshCare UI Initialized');
    
    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = new bootstrap.Alert(alert);
            bsAlert.close();
        }, 5000);
    });

    // Add red asterisk to required fields (label inferred by for= or nearby label).
    const addRequiredAsterisks = () => {
        const fields = document.querySelectorAll('input[required], select[required], textarea[required]');
        fields.forEach((field) => {
            if (field.type === 'hidden') return;
            if (field.hasAttribute('data-no-asterisk')) return;

            let label = null;
            const id = field.getAttribute('id');
            if (id) {
                label = document.querySelector(`label[for="${CSS.escape(id)}"]`);
            }

            if (!label) {
                const prev = field.previousElementSibling;
                if (prev && prev.tagName === 'LABEL') label = prev;
            }

            if (!label) {
                const wrap = field.closest('.mb-3, .form-group, .col, .row, .input-group, .modal-body, form');
                if (wrap) {
                    const candidate = wrap.querySelector('label');
                    if (candidate) label = candidate;
                }
            }

            if (!label) return;
            const labelText = (label.textContent || '').toLowerCase();
            if (labelText.includes('optional')) return;
            if (label.querySelector('.required-asterisk')) return;

            const star = document.createElement('span');
            star.className = 'required-asterisk';
            star.setAttribute('aria-hidden', 'true');
            star.textContent = '*';
            label.appendChild(star);
        });
    };

    addRequiredAsterisks();
});
