/* =========================================================================
   Script مشترکِ ظاهر جدید — بسیار سبک (۳ کیلوبایت، بدون وابستگی)
   وظایف: سوییچ تم · آشکارسازی تدریجی · بارگذاری تنبلِ بخش‌ها · شمارش معکوس
   ========================================================================= */
(function () {
    "use strict";

    /* ---------- ۱) سوییچ تم ---------- */
    function applyTheme(mode) {
        if (mode === 'dark' || mode === 'light') document.documentElement.setAttribute('data-theme', mode);
        else document.documentElement.removeAttribute('data-theme');
        document.querySelectorAll('.nx-theme').forEach(function (b) {
            b.setAttribute('aria-pressed', String(document.documentElement.getAttribute('data-theme') === 'dark'));
        });
    }
    window.nxApplyTheme = applyTheme;
    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('.nx-theme');
        if (!btn) return;
        var isDark = document.documentElement.getAttribute('data-theme') === 'dark';
        var next = isDark ? 'light' : 'dark';
        try { localStorage.setItem('nx-theme', next); } catch (err) { }
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
        var items = (root || document).querySelectorAll('.nx-reveal:not(.in)');
        if (!revealIO) { items.forEach(function (el) { el.classList.add('in'); }); return; }
        items.forEach(function (el) { revealIO.observe(el); });
    }

    /* ---------- ۳) بارگذاری تنبلِ بخش‌ها (data-nx-src) ---------- */
    var lazyIO = ('IntersectionObserver' in window) ? new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
            if (!en.isIntersecting) return;
            lazyIO.unobserve(en.target);
            loadSection(en.target);
        });
    }, { rootMargin: '320px 0px' }) : null;

    function loadSection(box) {
        var url = box.getAttribute('data-nx-src');
        if (!url || box.dataset.nxLoaded) return;
        box.dataset.nxLoaded = '1';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.text() : Promise.reject(new Error(r.status)); })
            .then(function (html) {
                box.innerHTML = html;
                reveal(box);
                document.dispatchEvent(new CustomEvent('nx:loaded', { detail: { box: box } }));
            })
            .catch(function () {
                box.innerHTML = '<div class="nx-empty"><div class="nx-empty-t">بارگذاری انجام نشد</div>' +
                    '<div class="nx-empty-d">اتصال اینترنت را بررسی کنید.</div>' +
                    '<button class="nx-btn nx-btn-outline nx-btn-sm" style="margin-top:12px" onclick="this.closest(\'[data-nx-src]\').removeAttribute(\'data-nx-loaded\');window.nxLoad(this.closest(\'[data-nx-src]\'))">تلاش دوباره</button></div>';
            });
    }
    window.nxLoad = loadSection;

    /* ---------- ۴) شمارش معکوس آزمون‌ها ---------- */
    function fa(n) { return String(n).replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; }); }
    function tick() {
        var now = Date.now();
        document.querySelectorAll('.nx-countdown[data-deadline]').forEach(function (el) {
            var end = Number(el.getAttribute('data-deadline'));
            var start = Number(el.getAttribute('data-start') || 0) * 1000;
            var diff = end - now;
            if (start > now) {
                el.textContent = 'شروع در ' + fa(Math.max(0, Math.ceil((start - now) / 60000))) + ' دقیقه';
                el.className = 'nx-countdown';
                return;
            }
            if (diff <= 0) { el.textContent = 'زمان پایان یافت'; el.className = 'nx-countdown end'; return; }
            var h = Math.floor(diff / 3600000), m = Math.floor((diff % 3600000) / 60000), s = Math.floor((diff % 60000) / 1000);
            var txt = h > 0 ? fa(h) + ':' + fa(m).padStart(2, '۰') + ':' + fa(s).padStart(2, '۰')
                : fa(m) + ':' + fa(s).padStart(2, '۰');
            el.textContent = txt + ' مانده';
            el.className = 'nx-countdown' + (diff < 300000 ? ' warn' : '');
        });
    }

    /* ---------- ۵) بستن اطلاعیه (مخفی‌سازی پایدار) ---------- */
    document.addEventListener('click', function (e) {
        var x = e.target.closest && e.target.closest('.nx-ann-x');
        if (!x) return;
        var ann = x.closest('.nx-ann');
        var id = ann && ann.getAttribute('data-ann-id');
        if (id) {
            try {
                var list = JSON.parse(localStorage.getItem('nx-ann-dismissed') || '[]');
                if (list.indexOf(id) < 0) list.push(id);
                localStorage.setItem('nx-ann-dismissed', JSON.stringify(list.slice(-60)));
            } catch (err) { }
        }
        if (ann) {
            ann.style.transition = 'opacity .25s,transform .25s';
            ann.style.opacity = '0';
            ann.style.transform = 'translateY(-6px)';
            setTimeout(function () {
                ann.remove();
                var box = document.querySelector('.nx-anns');
                if (box && !box.children.length) {
                    var card = box.closest('.nx-card');
                    if (card) card.remove();
                }
            }, 250);
        }
    });

    function hideDismissed() {
        var list = [];
        try { list = JSON.parse(localStorage.getItem('nx-ann-dismissed') || '[]'); } catch (e) { }
        if (!list.length) return;
        list.forEach(function (id) {
            var el = document.querySelector('.nx-ann[data-ann-id="' + id + '"]');
            if (el) el.remove();
        });
        var box = document.querySelector('.nx-anns');
        if (box && !box.children.length) { var card = box.closest('.nx-card'); if (card) card.remove(); }
    }

    /* ---------- ۶) نمایش بیشتر ---------- */
    document.addEventListener('click', function (e) {
        var btn = e.target.closest && e.target.closest('[data-nx-more]');
        if (!btn || btn.dataset.nxBusy) return;
        btn.dataset.nxBusy = '1';
        var target = document.querySelector(btn.getAttribute('data-nx-more'));
        fetch(btn.getAttribute('data-nx-url'), {
            headers: { 'X-Requested-With': 'XMLHttpRequest' }, credentials: 'same-origin'
        }).then(function (r) { return r.ok ? r.text() : Promise.reject(new Error(r.status)); })
            .then(function (html) {
                if (target) target.insertAdjacentHTML('beforeend', html);
                reveal(target);
                var left = btn.getAttribute('data-nx-left');
                if (!html.trim() || left === '0') btn.remove();
                else { delete btn.dataset.nxBusy; }
            }).catch(function () { delete btn.dataset.nxBusy; });
    });

    /* ---------- ۷) منوی کشوییِ موبایل (نوار بالای صفحهٔ هوم) ---------- */
    function initNavDrawer() {
        var burger = document.getElementById('nxNavBurger');
        var drawer = document.getElementById('nxNavDrawer');
        if (!burger || !drawer) return;

        function setOpen(open) {
            drawer.classList.toggle('open', open);
            burger.setAttribute('aria-expanded', String(open));
            burger.setAttribute('aria-label', open ? 'بستن منو' : 'باز کردن منو');
        }
        function close() { setOpen(false); }

        burger.addEventListener('click', function (e) {
            e.stopPropagation();
            setOpen(!drawer.classList.contains('open'));
        });
        // با انتخاب هر پیوند یا کلیک بیرون، کشو بسته می‌شود
        drawer.addEventListener('click', function (e) {
            if (e.target.closest && e.target.closest('a')) close();
        });
        document.addEventListener('click', function (e) {
            if (drawer.classList.contains('open') &&
                !drawer.contains(e.target) && !burger.contains(e.target)) close();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') close();
        });
        // در عرض دسکتاپ کشو بی‌معناست؛ بازِ فراموش‌شده بسته می‌شود
        var mq = window.matchMedia ? window.matchMedia('(min-width:900px)') : null;
        if (mq) {
            var onMq = function (ev) { if (ev.matches) close(); };
            if (mq.addEventListener) mq.addEventListener('change', onMq);
            else if (mq.addListener) mq.addListener(onMq);
        }
    }

    /* ---------- راه‌اندازی ---------- */
    function init() {
        hideDismissed();
        initNavDrawer();
        reveal(document);
        document.querySelectorAll('[data-nx-src]').forEach(function (box) {
            if (lazyIO) lazyIO.observe(box); else loadSection(box);
        });
        if (document.querySelector('.nx-countdown[data-deadline]')) { tick(); setInterval(tick, 1000); }
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})();
