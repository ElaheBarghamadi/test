"""
پردازش و اعتبارسنجی یکپارچهٔ فرم سوال — مشترک بین «سوال آزمون» و «بانک سوال».

parse_question_post(request, for_bank=False, existing=None) -> (data, error)
    data: دیکشنری فیلدهای مدل (text, question_type, max_score, options, options_type,
          correct_answer, blanks, matching_pairs, allow_image_answer)
    error: متن خطا (فارسی) یا None

قالب ورودی‌ها (نام فیلدهای فرم):
    تستی:        option_1..option_6 (متن)، option_image_N (فایل)، option_keep_N (آدرس تصویر فعلی)
                 correct_answer = شمارهٔ «اسلات» گزینهٔ صحیح؛ گزینه‌های خالی حذف و شماره‌ها بازچینی می‌شوند.
                 سازگاری با فرم قدیم: option1..option4 یا textarea «options» (هر خط یک گزینه)
    صحیح/غلط:    correct_answer = true | false
    جاخالی:      blank_label_N / blank_answer_N (N از ۰) — یا فرم قدیم: blanks و correct_answer با ویرگول
                 چند پاسخ قابل‌قبول برای یک جای خالی با «/» جدا می‌شوند: «۴۹/چهل و نه»
    وصل‌کردنی:   left_N / right_N (N از ۰) — حداقل دو جفت کامل
    کوتاه/بلند/تصویری: correct_answer = پاسخ مورد انتظار / معیار تصحیح (اختیاری)
"""
import os
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.files.storage import default_storage

VALID_TYPES = ('true_false', 'multiple_choice', 'fill_blank', 'short_answer',
               'long_answer', 'image_answer', 'matching')
MAX_OPTIONS = 6
MAX_PAIRS = 12
MAX_BLANKS = 12
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
MAX_IMAGE_BYTES = 2 * 1024 * 1024


def _clean(value, limit=2000):
    return (value or '').strip()[:limit]


def _score(raw):
    try:
        val = round(Decimal(str(raw).strip().replace('٫', '.')), 2)
    except (InvalidOperation, ValueError, TypeError):
        return None
    return val if val > 0 else None


def _save_option_image(upload):
    """ذخیرهٔ تصویر گزینه؛ خروجی آدرس قابل نمایش یا (None, خطا)"""
    ext = os.path.splitext(upload.name or '')[1].lower()
    if ext not in IMAGE_EXTS:
        return None, 'فرمت تصویر گزینه مجاز نیست (JPG, PNG, GIF, WEBP).'
    if upload.size > MAX_IMAGE_BYTES:
        return None, 'حجم تصویر گزینه نباید بیشتر از ۲ مگابایت باشد.'
    name = default_storage.save('question_images/options/opt_%s%s' % (uuid.uuid4().hex, ext), upload)
    return settings.MEDIA_URL + name, None


def _is_image_value(value):
    v = str(value or '').lower().split('?')[0]
    return v.startswith(settings.MEDIA_URL.lower()) and v.endswith(IMAGE_EXTS)


def _parse_options(post, files):
    """خروجی: (options, options_type, correct_index_str, error)"""
    slots = []   # (slot_number, value)
    explicit = any(k.startswith('option_') for k in post.keys()) or any(k.startswith('option_image_') for k in files.keys())
    legacy_numbered = any(post.get('option%d' % i) for i in range(1, 5))
    if explicit:
        for i in range(1, MAX_OPTIONS + 1):
            upload = files.get('option_image_%d' % i)
            text = _clean(post.get('option_%d' % i), 500)
            keep = _clean(post.get('option_keep_%d' % i), 500)
            if post.get('option_remove_%d' % i):
                keep = ''
            if upload:
                url, err = _save_option_image(upload)
                if err:
                    return None, None, None, err
                slots.append((i, url))
            elif text:
                slots.append((i, text))
            elif keep and _is_image_value(keep):
                slots.append((i, keep))
    elif legacy_numbered:
        for i in range(1, 5):
            text = _clean(post.get('option%d' % i), 500)
            if text:
                slots.append((i, text))
    else:
        lines = [l.strip() for l in (post.get('options') or '').splitlines() if l.strip()]
        slots = list(enumerate(lines[:MAX_OPTIONS], start=1))

    if len(slots) < 2:
        return None, None, None, 'برای سوال تستی حداقل دو گزینه لازم است.'
    values = [v for _, v in slots]
    if len(set(values)) != len(values):
        return None, None, None, 'گزینه‌های سوال تستی نباید تکراری باشند.'
    correct = _clean(post.get('correct_answer'), 5)
    slot_numbers = [s for s, _ in slots]
    if not correct.isdigit() or int(correct) not in slot_numbers:
        return None, None, None, 'پاسخ صحیح باید شمارهٔ یکی از گزینه‌های واردشده باشد.'
    new_index = slot_numbers.index(int(correct)) + 1
    images = sum(1 for v in values if _is_image_value(v))
    otype = 'text' if images == 0 else ('image' if images == len(values) else 'mixed')
    return values, otype, str(new_index), None


def _parse_blanks(post):
    """خروجی: (labels, correct_answer, error)"""
    rows_mode = any(k.startswith('blank_answer_') for k in post.keys())
    if rows_mode:
        labels, answers = [], []
        for i in range(MAX_BLANKS):
            ans = _clean(post.get('blank_answer_%d' % i), 300).replace(',', '،')
            lab = _clean(post.get('blank_label_%d' % i), 120).replace(',', '،')
            if not ans and not lab:
                continue
            if not ans:
                return None, None, 'پاسخ جای خالی %d را بنویسید.' % (len(answers) + 1)
            labels.append(lab)
            answers.append(ans)
        if not answers:
            return None, None, 'برای سوال جاخالی، دست‌کم یک جای خالی با پاسخ لازم است.'
        if not any(labels):
            labels = [''] * len(answers)
        return labels, ', '.join(answers), None

    labels = [b.strip() for b in (post.get('blanks') or '').replace('،', ',').split(',') if b.strip()]
    correct = _clean(post.get('correct_answer'), 2000)
    if not correct:
        return None, None, 'برای سوال جاخالی، پاسخ جاهای خالی را (با ویرگول) بنویسید.'
    answers = [a.strip() for a in correct.replace('،', ',').split(',') if a.strip()]
    if labels and len(labels) != len(answers):
        return None, None, 'تعداد پاسخ‌ها (%d) با تعداد جاهای خالی (%d) برابر نیست.' % (len(answers), len(labels))
    return labels, ', '.join(answers), None


def _parse_pairs(post):
    pairs = []
    for i in range(MAX_PAIRS * 2):
        left = _clean(post.get('left_%d' % i), 300)
        right = _clean(post.get('right_%d' % i), 300)
        if not left and not right:
            continue
        if not left or not right:
            return None, 'در سوال وصل‌کردنی، هر دو طرف جفت %d باید پر شود.' % (len(pairs) + 1)
        pairs.append({'left': left, 'right': right})
    if len(pairs) < 2:
        return None, 'سوال وصل‌کردنی دست‌کم به دو جفت کامل نیاز دارد.'
    if len(pairs) > MAX_PAIRS:
        return None, 'حداکثر %d جفت مجاز است.' % MAX_PAIRS
    rights = [p['right'] for p in pairs]
    if len(set(rights)) != len(rights):
        return None, 'گزینه‌های ستون دوم وصل‌کردنی نباید تکراری باشند.'
    return pairs, None


def parse_question_post(request, for_bank=False):
    post, files = request.POST, request.FILES
    qtype = post.get('question_type', '')
    text = _clean(post.get('text'), 10000)
    if qtype not in VALID_TYPES:
        return None, 'نوع سوال را به‌درستی انتخاب کنید.'
    if not text and not files.get('image') and not post.get('keep_image'):
        return None, 'متن سوال الزامی است.'

    raw_score = post.get('max_score', '1' if for_bank else '')
    score = _score(raw_score if str(raw_score).strip() else ('1' if for_bank else ''))
    if score is None:
        return None, 'بارم سوال باید عددی بزرگ‌تر از صفر باشد.'

    data = {
        'text': text, 'question_type': qtype, 'max_score': score,
        'options': [], 'options_type': 'text', 'correct_answer': None,
        'blanks': [], 'matching_pairs': [],
        'allow_image_answer': bool(post.get('allow_image_answer')) or qtype == 'image_answer',
    }
    correct = _clean(post.get('correct_answer'), 10000) or None

    if qtype == 'multiple_choice':
        options, otype, idx, err = _parse_options(post, files)
        if err:
            return None, err
        data.update(options=options, options_type=otype, correct_answer=idx)
    elif qtype == 'true_false':
        if correct not in ('true', 'false'):
            return None, 'برای سوال صحیح/غلط، پاسخ صحیح را انتخاب کنید.'
        data['correct_answer'] = correct
    elif qtype == 'fill_blank':
        labels, answer, err = _parse_blanks(post)
        if err:
            return None, err
        data.update(blanks=labels, correct_answer=answer)
    elif qtype == 'matching':
        pairs, err = _parse_pairs(post)
        if err:
            return None, err
        data['matching_pairs'] = pairs
    elif qtype == 'short_answer':
        if for_bank and not correct:
            return None, 'برای سوال پاسخ کوتاه، پاسخ مورد انتظار را بنویسید.'
        data['correct_answer'] = correct
    else:  # long_answer / image_answer
        data['correct_answer'] = correct
    return data, None


def matching_answer_key(question_id, pairs):
    """کلید پاسخ وصل‌کردنی به همان قالبی که صفحهٔ آزمون ذخیره می‌کند"""
    import json
    return json.dumps({'pair_%s_%d' % (question_id, i): 'pair_%s_%d' % (question_id, i)
                       for i in range(len(pairs or []))}, ensure_ascii=False)


def apply_to_question(question, data):
    """اعمال داده روی یک Question (بدون ذخیره)؛ فیلدهای نامرتبط با نوع پاک می‌شوند"""
    for key, value in data.items():
        setattr(question, key, value)


def finalize_question(question):
    """پس از ذخیره (وقتی id داریم): کلید پاسخ وصل‌کردنی ساخته می‌شود"""
    if question.question_type == 'matching':
        key = matching_answer_key(question.id, question.matching_pairs)
        if question.correct_answer != key:
            question.correct_answer = key
            question.save(update_fields=['correct_answer'])
