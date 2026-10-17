/* =========================================================================
   اسکریپت مشترک سایت — سبک و بدون وابستگی.

   وظایف: سوییچ تم · آشکارسازی تدریجی · بارگذاری تنبل بخش‌ها ·
          شمارش معکوس آزمون · بستن اطلاعیه‌ها · «نمایش بیشتر»

   همهٔ قلاب‌ها data-attribute خنثی هستند و به نام کلاس‌های CSS گره نخورده‌اند،
   تا عوض‌شدن سیستم طراحی، رفتار را نشکند:
     [data-theme-toggle] [data-reveal] [data-lazy-src] [data-countdown]
     [data-ann-id] [data-ann-close] [data-ann-list]
     [data-load-more] + data-url + data-left
   ========================================================================= */
(function () {
    "use strict";

    var THEME_KEY = 'site-theme';
    var ANN_KEY = 'ann-dismissed';

    function fa(n) { return String(n).replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; }); }

    /* ---------- ۱) سوییچ تم ---------- */
    function applyTheme(mode) {
        if (mode === 'dark' || mode === 'light') document.documentElement.setAttribute('data-theme', mode);
        else document.documentElement.removeAttribute('data-theme');
        var dark = document.documentElement.getAttribute('data-theme') === 'dark';
        document.querySelectorAll('[data-theme-toggle]').forEach(function (b) {
            b.setAttribute('aria-pressed', String(dark));
        });
    }

    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('[data-theme-toggle]');
        if (!btn) return;
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var next = isDark ? 'light' : 'dark';
        try { localStorage.setItem(THEME_KEY, next); } catch (err) { /* حالت خصوصی */ }
        applyTheme(next);
    });

    /* ---------- ۲) آشکارسازی تدریجی ---------- */
    var revealIO = ('IntersectionObserver' in window) ? new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            en.target.classList.add('in');
            revealIO.unobserve(en.target);
        });
    }, { rootMargin: '0px 0px -8% 0px', threshold: .05 }) : null;

    function reveal(root) {
        var items = (root || document).querySelectorAll('[data-reveal]:not(.in)');
        if (!revealIO) { items.forEach(function (el) { el.classList.add('in'); }); return; }
        items.forEach(function (el) { revealIO.observe(el); });
    }

    /* ---------- ۳) بارگذاری تنبلِ بخش‌ها ---------- */
    var lazyIO = ('IntersectionObserver' in window) ? new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            lazyIO.unobserve(en.target);
            loadSection(en.target);
        });
    }, { rootMargin: '320px 0px' }) : null;

    function loadSection(box) {
        var url = box.getAttribute('data-lazy-src');
        if (!url || box.dataset.lazyLoaded) return;
        box.dataset.lazyLoaded = '1';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.text() : Promise.reject(new Error(r.status)); })
            .then(function (html) {
                box.innerHTML = html;
                reveal(box);
                initCountdowns(box);
                document.dispatchEvent(new CustomEvent('lazy:loaded', { detail: { box: box } }));
            })
            .catch(function () {
                delete box.dataset.lazyLoaded;
                box.innerHTML =
                    '<div class="empty-state"><p><b>بارگذاری این بخش انجام نشد</b></p>' +
                    '<p>اتصال اینترنت را بررسی کنید و دوباره تلاش کنید.</p>' +
                    '<button type="button" class="btn btn-sm" data-lazy-retry>تلاش دوباره</button></div>';
            });
    }

    document.addEventListener('click', function (e) {
        var retry = e.target.closest && e.target.closest('[data-lazy-retry]');
        if (!retry) return;
        var box = retry.closest('[data-lazy-src]');
        if (box) loadSection(box);
    });

    /* ---------- ۴) شمارش معکوس آزمون‌ها ---------- */
    function tickOne(el, now) {
        var end = Number(el.getAttribute('data-deadline'));
        var start = Number(el.getAttribute('data-start') || 0) * 1000;
        // classList به‌جای className: کلاس‌های دیگرِ عنصر پاک نمی‌شوند
        el.classList.remove('warn', 'end');

        if (start > now) {
            el.textContent = 'شروع در ' + fa(Math.max(0, Math.ceil((start - now) / 60000))) + ' دقیقه';
            return;
        }
        var diff = end - now;
        if (diff <= 0) { el.textContent = 'زمان پایان یافت'; el.classList.add('end'); return; }

        var h = Math.floor(diff / 3600000),
            m = Math.floor((diff % 3600000) / 60000),
            s = Math.floor((diff % 60000) / 1000);
        el.textContent = (h > 0
            ? fa(h) + ':' + fa(m).padStart(2, '۰') + ':' + fa(s).padStart(2, '۰')
            : fa(m) + ':' + fa(s).padStart(2, '۰')) + ' مانده';
        if (diff < 300000) el.classList.add('warn');
    }

    var countdownTimer = null;
    function initCountdowns(root) {
        var items = (root || document).querySelectorAll('[data-countdown]');
        if (!items.length) return;
        var now = Date.now();
        items.forEach(function (el) { tickOne(el, now); });
        if (countdownTimer) return;
        countdownTimer = setInterval(function () {
            var t = Date.now();
            document.querySelectorAll('[data-countdown]').forEach(function (el) { tickOne(el, t); });
        }, 1000);
    }

    /* ---------- ۵) بستن اطلاعیه (مخفی‌سازی پایدار) ---------- */
    function readDismissed() {
        try { return JSON.parse(localStorage.getItem(ANN_KEY) || '[]'); } catch (e) { return []; }
    }

    function dropEmptyList() {
        document.querySelectorAll('[data-ann-list]').forEach(function (list) {
            if (list.children.length) return;
            var card = list.closest('.card') || list.closest('.announce-card');
            if (card) card.remove();
        });
    }

    document.addEventListener('click', function (e) {
        var x = e.target.closest && e.target.closest('[data-ann-close]');
        if (!x) return;
        var ann = x.closest('[data-ann-id]');
        var id = ann && ann.getAttribute('data-ann-id');
        if (id) {
            var list = readDismissed();
            if (list.indexOf(id) < 0) list.push(id);
            try { localStorage.setItem(ANN_KEY, JSON.stringify(list.slice(-60))); } catch (err) { }
        }
        if (!ann) return;
        ann.style.transition = 'opacity .25s,transform .25s';
        ann.style.opacity = '0';
        ann.style.transform = 'translateY(-6px)';
        setTimeout(function () { ann.remove(); dropEmptyList(); }, 250);
    });

    function hideDismissed() {
        var list = readDismissed();
        if (!list.length) return;
        list.forEach(function (id) {
            var el = document.querySelector('[data-ann-id="' + id + '"]');
            if (el) el.remove();
        });
        dropEmptyList();
    }

    /* ---------- ۶) نمایش بیشتر ---------- */
    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('[data-load-more]');
        if (!btn || btn.dataset.busy) return;
        btn.dataset.busy = '1';
        var target = document.querySelector(btn.getAttribute('data-load-more'));
        fetch(btn.getAttribute('data-url'), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
        }).then(function (r) { return r.ok ? r.text() : Promise.reject(new Error(r.status)); })
            .then(function (html) {
                if (target) {
                    target.insertAdjacentHTML('beforeend', html);
                    reveal(target);
                    initCountdowns(target);
                }
                if (!html.trim() || btn.getAttribute('data-left') === '0') btn.remove();
                else delete btn.dataset.busy;
            })
            .catch(function () { delete btn.dataset.busy; });
    });


    /* ---------- راه‌اندازی ---------- */
    function init() {
        try {
            var saved = localStorage.getItem(THEME_KEY);
            if (saved) applyTheme(saved);
        } catch (err) { }
        hideDismissed();
        reveal(document);
        document.querySelectorAll('[data-lazy-src]').forEach(function (box) {
            if (lazyIO) lazyIO.observe(box); else loadSection(box);
        });
        initCountdowns(document);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();

    window.AppTheme = applyTheme;
    window.AppLazy = { load: loadSection, reveal: reveal };
})();
