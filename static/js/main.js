// Sidebar toggle
const sidebar = document.getElementById('sidebar');
const mainContent = document.getElementById('mainContent');
const sidebarToggle = document.getElementById('sidebarToggle');

if (sidebarToggle) {
  sidebarToggle.addEventListener('click', () => {
    if (window.innerWidth <= 768) {
      sidebar.classList.toggle('open');
    } else {
      sidebar.classList.toggle('collapsed');
      mainContent.classList.toggle('expanded');
    }
  });
}

// ── ANIMATIONS & UX ───────────────────────────

document.addEventListener('DOMContentLoaded', function() {
  // 6. LOADING SPINNER ON FORM SUBMIT
  const forms = document.querySelectorAll('form');
  
  forms.forEach(form => {
      form.addEventListener('submit', function(e) {
          // Find the submit button
          const submitBtn = form.querySelector('button[type="submit"]');
          if (submitBtn && !submitBtn.classList.contains('loading')) {
              // Add spinner element if not present
              if (!submitBtn.querySelector('.btn-spinner')) {
                  const spinnerSpan = document.createElement('span');
                  spinnerSpan.className = 'spinner-border spinner-border-sm btn-spinner';
                  spinnerSpan.setAttribute('role', 'status');
                  spinnerSpan.setAttribute('aria-hidden', 'true');
                  submitBtn.prepend(spinnerSpan);
              }
              
              // Add loading class to disable and show spinner
              submitBtn.classList.add('loading');
          }
      });
  });

  // 8. SCROLL ANIMATION using Intersection Observer
  const animatedElements = document.querySelectorAll('.fade-in-scroll');
  
  if (animatedElements.length > 0) {
      const observer = new IntersectionObserver((entries) => {
          entries.forEach(entry => {
              if (entry.isIntersecting) {
                  entry.target.classList.add('visible');
                  // Unobserve after animating once
                  observer.unobserve(entry.target);
              }
          });
      }, {
          root: null,
          threshold: 0.1, // Trigger when 10% is visible
          rootMargin: '0px 0px -50px 0px'
      });

      animatedElements.forEach(el => {
          observer.observe(el);
      });
  }
});

// Auto-dismiss alerts after 5 seconds
document.querySelectorAll('.alert').forEach(alert => {
  setTimeout(() => {
    const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
    if (bsAlert) bsAlert.close();
  }, 5000);
});

