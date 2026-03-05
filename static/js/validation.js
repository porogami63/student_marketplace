/**
 * Form Validation Script
 * Provides real-time validation feedback with pop-up warnings
 */

// Validation rules for different field types
const VALIDATION_RULES = {
    username: {
        pattern: /^[a-zA-Z0-9_-]+$/,
        minLength: 3,
        maxLength: 20,
        messages: {
            required: 'Username is required',
            minLength: 'Username must be at least 3 characters',
            maxLength: 'Username must be 20 characters or less',
            pattern: 'Username can only contain letters, numbers, hyphens, and underscores'
        }
    },
    email: {
        pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
        messages: {
            required: 'Email is required',
            pattern: 'Please enter a valid email address'
        }
    },
    phone: {
        pattern: /^[0-9+\-\s()]{7,20}$/,
        minLength: 7,
        maxLength: 20,
        messages: {
            pattern: 'Please enter a valid phone number (7-20 characters)',
            minLength: 'Phone number must be at least 7 characters',
            maxLength: 'Phone number must be 20 characters or less'
        }
    },
    price: {
        min: 0,
        max: 999999,
        messages: {
            required: 'Price is required',
            min: 'Price must be greater than 0',
            max: 'Price cannot exceed ₱999,999'
        }
    },
    age: {
        min: 10,
        max: 80,
        messages: {
            min: 'You must be at least 10 years old',
            max: 'Please enter a valid age (80 or less)'
        }
    },
    title: {
        minLength: 5,
        maxLength: 200,
        messages: {
            required: 'Title is required',
            minLength: 'Title must be at least 5 characters',
            maxLength: 'Title must be 200 characters or less'
        }
    },
    description: {
        minLength: 10,
        maxLength: 2000,
        messages: {
            minLength: 'Description must be at least 10 characters',
            maxLength: 'Description must be 2000 characters or less'
        }
    }
};

/**
 * Show a validation error/warning
 * @param {HTMLElement} field - The form field
 * @param {string} message - The error message
 */
function showValidationWarning(field, message) {
    // Remove existing warning
    removeValidationWarning(field);
    
    // Add error styling
    field.classList.add('is-invalid');
    field.style.borderColor = '#dc3545';
    
    // Create and insert error message element
    const errorDiv = document.createElement('div');
    errorDiv.className = 'invalid-feedback d-block mt-1';
    errorDiv.style.cssText = 'color: #dc3545; font-size: 0.875rem; margin-top: 0.25rem;';
    errorDiv.textContent = message;
    errorDiv.id = `error-${field.id || field.name}`;
    
    // Insert after field
    if (field.nextElementSibling && field.nextElementSibling.classList && 
        field.nextElementSibling.classList.contains('invalid-feedback')) {
        field.nextElementSibling.remove();
    }
    field.parentNode.insertBefore(errorDiv, field.nextSibling);
    
    // Show toast notification for important errors
    if (['price', 'title'].includes(field.name)) {
        showToastWarning(`Validation: ${message}`);
    }
}

/**
 * Remove validation warning from a field
 * @param {HTMLElement} field - The form field
 */
function removeValidationWarning(field) {
    field.classList.remove('is-invalid');
    field.style.borderColor = '';
    
    const errorDiv = document.getElementById(`error-${field.id || field.name}`);
    if (errorDiv) {
        errorDiv.remove();
    }
}

/**
 * Show a toast warning message
 * @param {string} message - The message to display
 */
function showToastWarning(message) {
    const toastContainer = document.getElementById('toast-container') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = 'toast-warning';
    toast.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #fff3cd;
        border: 1px solid #ffc107;
        color: #856404;
        padding: 15px 20px;
        border-radius: 8px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
        z-index: 9999;
        animation: slideIn 0.3s ease-in-out;
        font-size: 0.95rem;
    `;
    toast.textContent = message;
    
    toastContainer.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease-in-out';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

/**
 * Create a toast container if it doesn't exist
 */
function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
    return container;
}

/**
 * Validate a single field
 * @param {HTMLElement} field - The form field to validate
 * @returns {boolean} - True if valid, false otherwise
 */
function validateField(field) {
    const fieldName = field.name || field.id;
    const fieldType = field.type || 'text';
    const value = field.value.trim();
    
    // Skip validation for empty optional fields (not required)
    if (!value && !field.required) {
        removeValidationWarning(field);
        return true;
    }
    
    // Check required
    if (field.required && !value) {
        const message = VALIDATION_RULES[fieldName]?.messages?.required || 'This field is required';
        showValidationWarning(field, message);
        return false;
    }
    
    // Get rules for this field  
    const rules = VALIDATION_RULES[fieldName];
    if (!rules && !field.hasAttribute('minlength') && !field.hasAttribute('maxlength')) {
        removeValidationWarning(field);
        return true;
    }
    
    // Apply HTML5 validation attributes if no custom rules
    if (field.checkValidity) {
        if (!field.checkValidity()) {
            const validityState = field.validity;
            let message = 'Please check this field';
            
            if (validityState.valueMissing) {
                message = 'This field is required';
            } else if (validityState.typeMismatch) {
                message = `Please enter a valid ${fieldType}`;
            } else if (validityState.tooShort) {
                message = `Must be at least ${field.minLength} characters`;
            } else if (validityState.tooLong) {
                message = `Must be at most ${field.maxLength} characters`;
            } else if (validityState.rangeUnderflow) {
                message = `Value must be at least ${field.min}`;
            } else if (validityState.rangeOverflow) {
                message = `Value must be at most ${field.max}`;
            } else if (validityState.patternMismatch) {
                message = field.title || 'Please check the format';
            }
            
            showValidationWarning(field, message);
            return false;
        }
    }
    
    removeValidationWarning(field);
    return true;
}

/**
 * Validate entire form
 * @param {HTMLFormElement} form - The form to validate
 * @returns {boolean} - True if all fields are valid
 */
function validateForm(form) {
    if (!form) return true;
    
    let isValid = true;
    const fields = form.querySelectorAll('input, textarea, select');
    
    fields.forEach(field => {
        // Skip hidden fields and submit buttons
        if (field.type === 'hidden' || field.type === 'submit' || !field.offsetParent) {
            return;
        }
        
        if (!validateField(field)) {
            isValid = false;
        }
    });
    
    return isValid;
}

// Initialize validation on page load
document.addEventListener('DOMContentLoaded', function() {
    // Add real-time validation to all form fields
    const allFields = document.querySelectorAll('input, textarea, select');
    
    allFields.forEach(field => {
        // Skip hidden fields
        if (field.type === 'hidden') return;
        
        // Validate on blur (when user leaves field)
        field.addEventListener('blur', function() {
            validateField(this);
        });
        
        // Real-time validation for specific fields
        if (['username', 'email', 'price', 'title', 'phone'].includes(this.name || this.id)) {
            field.addEventListener('input', function() {
                if (this.value) {
                    validateField(this);
                }
            });
        }
    });
    
    // Form submission validation
    const forms = document.querySelectorAll('form');
    forms.forEach(form => {
        form.addEventListener('submit', function(e) {
            if (!validateForm(this)) {
                e.preventDefault();
                showToastWarning('Please fix the errors above before submitting');
                return false;
            }
        });
    });
    
    // Add CSS styles for validation if not already present
    if (!document.querySelector('style[data-validation-style]')) {
        const style = document.createElement('style');
        style.setAttribute('data-validation-style', 'true');
        style.textContent = `
            .is-invalid {
                border-color: #dc3545 !important;
            }
            
            .invalid-feedback {
                display: block;
                color: #dc3545;
                font-size: 0.875rem;
                margin-top: 0.25rem;
            }
            
            @keyframes slideIn {
                from {
                    transform: translateX(400px);
                    opacity: 0;
                }
                to {
                    transform: translateX(0);
                    opacity: 1;
                }
            }
            
            @keyframes slideOut {
                from {
                    transform: translateX(0);
                    opacity: 1;
                }
                to {
                    transform: translateX(400px);
                    opacity: 0;
                }
            }
            
            input.is-invalid,
            textarea.is-invalid,
            select.is-invalid {
                background-image: none !important;
            }
            
            .form-control:focus {
                border-color: #80bdff;
                box-shadow: 0 0 0 0.2rem rgba(0, 123, 255, 0.25);
            }
            
            .form-control.is-invalid:focus {
                border-color: #dc3545;
                box-shadow: 0 0 0 0.2rem rgba(220, 53, 69, 0.25);
            }
        `;
        document.head.appendChild(style);
    }
});

// Export functions for external use
window.validateField = validateField;
window.validateForm = validateForm;
window.showValidationWarning = showValidationWarning;
window.showToastWarning = showToastWarning;
