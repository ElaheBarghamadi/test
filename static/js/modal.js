/* سیستم مودال یکپارچهٔ سایت — تنها پیاده‌سازی مودال.
 *
 * استفادهٔ declarative (بدون نوشتن حتی یک خط JS در قالب):
 *
 *   <button class="btn btn-primary" data-modal-open="groupModal">ساخت گروه</button>
 *
 *   <div class="modal-backdrop" id="groupModal">
 *     <div class="modal-card lg">
 *       <div class="modal-head">
 *         <div>
 *           <h3 class="modal-title">ساخت گروه</h3>
 *           <p class="modal-sub">دانش‌آموزان را با سرچ پیدا کنید</p>
 *         </div>
 *         <button type="button" class="modal-close" data-modal-close aria-label="بستن">×</button>
 *       </div>
 *       <div class="modal-body">…</div>
 *       <div class="modal-foot">
 *         <button type="button" class="btn btn-secondary" data-modal-close>انصراف</button>
 *         <button type="submit" class="btn btn-primary">ثبت</button>
 *       </div>
 *     </div>
 *   </div>
 *
 * استفادهٔ برنامه‌ای:  AppModal.open('groupModal')  /  AppModal.close('groupModal')
 * رویدادها: 'modal:open' و 'modal:close' روی خود backdrop (با bubbles)
 *
 * رفتار: Escape، کلیک روی پس‌زمینه، focus-trap، قفل اسکرول بدنه و بازگرداندن
 * فوکوس به دکمهٔ بازکننده. مودال‌های تودرتو با یک پشته مدیریت می‌شوند تا
 * Escape فقط بالایی‌ترین را ببندد و اسکرول زودهنگام باز نشود.
 */
(function () {
    'use strict';

    var FOCUSABLE = [
        'a[href]', 'button:not([disabled])', 'input:not([disabled]):not([type="hidden"])',
        'select:not([disabled])', 'textarea:not([disabled])', '[tabindex]:not([tabindex="-1"])'
    ].join(',');

    var stack = [];
    var opener = null;

    function visible(node) {
        return !!(node.offsetWidth || node.offsetHeight || node.getClientRects().length);
    }

    function focusables(card) {
        return Array.prototype.filter.call(card.querySelectorAll(FOCUSABLE), visible);
    }

    function cardOf(backdrop) {
        return backdrop.querySelector('.modal-card') || backdrop;
    }

    function open(id) {
        var backdrop = typeof id === 'string' ? document.getElementById(id) : id;
        if (!backdrop || backdrop.classList.contains('show')) return;

        if (!stack.length) opener = document.activeElement;

        backdrop.classList.add('show');
        backdrop.setAttribute('aria-hidden', 'false');
        document.body.classList.add('modal-open');

        var card = cardOf(backdrop);
        card.setAttribute('role', 'dialog');
        card.setAttribute('aria-modal', 'true');
        if (!card.hasAttribute('tabindex')) card.setAttribute('tabindex', '-1');

        stack.push(backdrop);

        var items = focusables(card);
        (items[0] || card).focus();

        backdrop.dispatchEvent(new CustomEvent('modal:open', { bubbles: true }));
    }

    function close(id) {
        var backdrop;
        if (id === undefined) {
            backdrop = stack[stack.length - 1];
        } else {
            backdrop = typeof id === 'string' ? document.getElementById(id) : id;
        }
        if (!backdrop || !backdrop.classList.contains('show')) return;

        backdrop.classList.remove('show');
        backdrop.setAttribute('aria-hidden', 'true');
        stack = stack.filter(function (m) { return m !== backdrop; });

        if (!stack.length) {
            document.body.classList.remove('modal-open');
            if (opener && typeof opener.focus === 'function') opener.focus();
            opener = null;
        }

        backdrop.dispatchEvent(new CustomEvent('modal:close', { bubbles: true }));
    }

    // --- سیم‌کشی خودکار: یک هندلر برای کل صفحه، نه یکی به ازای هر مودال ---
    document.addEventListener('click', function (e) {
        var trigger = e.target.closest('[data-modal-open]');
        if (trigger) {
            e.preventDefault();
            open(trigger.getAttribute('data-modal-open'));
            return;
        }
        if (e.target.closest('[data-modal-close]')) {
            e.preventDefault();
            close(e.target.closest('.modal-backdrop'));
            return;
        }
        // کلیک روی خودِ پس‌زمینه (نه کارت) مودال را می‌بندد
        if (e.target.classList && e.target.classList.contains('modal-backdrop') && e.target.classList.contains('show')) {
            close(e.target);
        }
    });

    document.addEventListener('keydown', function (e) {
        if (!stack.length) return;
        var top = stack[stack.length - 1];

        if (e.key === 'Escape') {
            e.preventDefault();
            close(top);
            return;
        }
        if (e.key !== 'Tab') return;

        var items = focusables(cardOf(top));
        if (!items.length) { e.preventDefault(); return; }
        var first = items[0], last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
        }
    });

    window.AppModal = { open: open, close: close, isOpen: function (id) { return !!stack.length; } };
})();

/* ==================== انتخاب‌گر چندتایی با جست‌وجو ====================
 * برای انتخاب دانش‌آموزان در مودال گروه‌ها (و هر فهرست بلند دیگری).
 *
 *   <div class="picker" data-picker>
 *     <input type="search" data-picker-search>
 *     <span data-picker-count></span>
 *     <button type="button" data-picker-all>انتخاب نتایج</button>
 *     <button type="button" data-picker-none>پاک‌کردن</button>
 *     <div data-picker-list>
 *       <label data-picker-item><input type="checkbox" name="students" value="1">…</label>
 *     </div>
 *   </div>
 *
 * هیچ قالبی برای این رفتار JS نمی‌نویسد؛ یک هندلر برای همهٔ انتخاب‌گرها.
 */
(function () {
    'use strict';

    var FA_DIGITS = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];

    function faNum(n) {
        return String(n).replace(/\d/g, function (d) { return FA_DIGITS[+d]; });
    }

    function normalize(s) {
        // یکسان‌سازی ی/ک عربی-فارسی و حذف اعراب تا سرچ فارسی درست کار کند
        return (s || '').toLowerCase()
            .replace(/[\u064B-\u0652\u0670\u0640]/g, '')
            .replace(/ي/g, 'ی').replace(/ك/g, 'ک')
            .replace(/\s+/g, ' ').trim();
    }

    function items(picker) {
        return Array.prototype.slice.call(picker.querySelectorAll('[data-picker-item]'));
    }

    function boxes(picker) {
        return Array.prototype.slice.call(picker.querySelectorAll('input[type="checkbox"]'));
    }

    function searchText(item) {
        return normalize(item.getAttribute('data-search') || item.textContent);
    }

    function visibleItems(picker) {
        return items(picker).filter(function (it) { return !it.hidden; });
    }

    function refresh(picker) {
        var count = boxes(picker).filter(function (b) { return b.checked; }).length;
        var out = picker.querySelector('[data-picker-count]');
        if (out) out.textContent = faNum(count) + ' انتخاب‌شده';

        var shown = visibleItems(picker).length;
        var none = picker.querySelector('[data-picker-empty]');
        if (none) none.hidden = shown !== 0;
    }

    function applyFilter(picker) {
        var input = picker.querySelector('[data-picker-search]');
        if (!input) return;
        var q = normalize(input.value);
        var terms = q ? q.split(' ') : [];
        items(picker).forEach(function (it) {
            var hay = searchText(it);
            it.hidden = terms.some(function (t) { return hay.indexOf(t) === -1; });
        });
        refresh(picker);
    }

    document.addEventListener('input', function (e) {
        var picker = e.target.closest('[data-picker]');
        if (picker && e.target.hasAttribute('data-picker-search')) applyFilter(picker);
    });

    document.addEventListener('change', function (e) {
        var picker = e.target.closest('[data-picker]');
        if (picker && e.target.type === 'checkbox') refresh(picker);
    });

    document.addEventListener('click', function (e) {
        var btn = e.target.closest('[data-picker-all],[data-picker-none]');
        if (!btn) return;
        e.preventDefault();
        var picker = btn.closest('[data-picker]');
        if (!picker) return;
        var all = btn.hasAttribute('data-picker-all');
        // فقط روی نتایجِ فیلترشده اثر می‌کند، نه کل فهرست
        visibleItems(picker).forEach(function (it) {
            it.querySelectorAll('input[type="checkbox"]').forEach(function (b) { b.checked = all; });
        });
        refresh(picker);
    });

    // Enter در فیلد سرچ نباید فرم را submit کند
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && e.target.hasAttribute && e.target.hasAttribute('data-picker-search')) {
            e.preventDefault();
        }
    });

    window.AppPicker = { refresh: refresh, applyFilter: applyFilter };
})();
