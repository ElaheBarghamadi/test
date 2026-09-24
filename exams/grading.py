"""تصحیح خودکار پاسخ‌های عینی (تستی/صحیح‌غلط/جاخالی/وصل‌کردنی) پس از ثبت نهایی آزمون."""
import json

from django.db import transaction


def _normalize_fa_text(value):
    """یکسان‌سازی متن فارسی برای مقایسه"""
    if value is None:
        return ''
    text = str(value).strip().lower()
    # ارقام فارسی/عربی به لاتین تا «۴۹» و «49» یکسان باشند
    text = text.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    text = text.replace('\u200c', ' ').replace('\u064a', 'ی').replace('\u0643', 'ک').replace('\u0629', 'ه')
    return ' '.join(text.split())


def _matches_any(given, expected_part):
    """پاسخ‌های قابل‌قبول یک جای خالی با «/» جدا می‌شوند: «۴۹/چهل و نه»"""
    options = [_normalize_fa_text(o) for o in str(expected_part).split('/') if o.strip()]
    return _normalize_fa_text(given) in options if options else False


def fill_blank_is_correct(answer_text, correct_answer):
    """مقایسه پاسخ جاخالی («مقدار۱ | مقدار۲») با پاسخ صحیح («مقدار۱, مقدار۲»)"""
    given = [p for p in str(answer_text or '').split('|')]
    expected = [p for p in str(correct_answer or '').replace('،', ',').split(',') if p.strip()]
    if not expected:
        return False
    if len(given) == 1 and len(expected) > 1:
        return _normalize_fa_text(given[0]) == _normalize_fa_text(correct_answer)
    return all(i < len(given) and _matches_any(given[i], want) for i, want in enumerate(expected))


def matching_is_correct(answer_text, correct_answer):
    """پاسخ وصل‌کردنی به‌صورت دیکشنری JSON ذخیره می‌شود؛ مقایسه کلیدبه‌کلید با پاسخ صحیح"""
    if not answer_text or not correct_answer:
        return False
    try:
        given = json.loads(answer_text)
        expected = json.loads(correct_answer)
    except (TypeError, ValueError):
        return False
    if not isinstance(given, dict) or not isinstance(expected, dict) or not expected:
        return False
    def idx(value):
        # «pair_12_3» ، «r_3» و … — فقط شمارهٔ انتهایی معیار است
        return str(value or '').strip().rsplit('_', 1)[-1]
    for key, want in expected.items():
        got = given.get(key, '')
        if not got or idx(got) != idx(want):
            return False
    return True


AUTO_TYPES = ('true_false', 'multiple_choice', 'fill_blank', 'matching')


def evaluate_answer(question, answer_text):
    """True/False برای سوالات عینی؛ None یعنی نیاز به تصحیح دستی"""
    if question.question_type not in AUTO_TYPES:
        return None
    correct = (question.correct_answer or '').strip()
    if question.question_type == 'matching' and question.matching_pairs:
        # کلید پاسخ همیشه از خود جفت‌ها ساخته می‌شود (جفت i ⟵ گزینهٔ i)
        from .question_forms import matching_answer_key
        correct = matching_answer_key(question.id, question.matching_pairs)
    if not correct:
        return None
    if not answer_text or not str(answer_text).strip():
        return False
    qtype = question.question_type
    if qtype in ('true_false', 'multiple_choice'):
        return str(answer_text).strip().lower() == correct.lower()
    if qtype == 'fill_blank':
        return fill_blank_is_correct(answer_text, correct)
    if qtype == 'matching':
        return matching_is_correct(answer_text, correct)
    return None


def _fill_blank_fraction(answer_text, correct_answer):
    given = str(answer_text or '').split('|')
    expected = [p for p in str(correct_answer or '').replace('،', ',').split(',') if p.strip()]
    if not expected:
        return None
    if len(given) == 1 and len(expected) > 1:
        return 1.0 if _normalize_fa_text(given[0]) == _normalize_fa_text(correct_answer) else 0.0
    ok = sum(1 for i, want in enumerate(expected) if i < len(given) and _matches_any(given[i], want))
    return ok / len(expected)


def _matching_fraction(answer_text, correct_answer):
    try:
        given = json.loads(answer_text or '{}')
        expected = json.loads(correct_answer or '{}')
    except (TypeError, ValueError):
        return 0.0
    if not isinstance(given, dict) or not isinstance(expected, dict) or not expected:
        return 0.0
    idx = lambda v: str(v or '').strip().rsplit('_', 1)[-1]
    ok = sum(1 for k, want in expected.items() if given.get(k) and idx(given.get(k)) == idx(want))
    return ok / len(expected)


def evaluate_fraction(question, answer_text):
    """کسر نمره (۰ تا ۱) برای سوالات عینی؛ جاخالی و وصل‌کردنی نمرهٔ جزئی می‌گیرند.
    None یعنی تصحیح دستی لازم است."""
    verdict = evaluate_answer(question, answer_text)
    if verdict is None:
        return None
    if verdict:
        return 1.0
    if not answer_text or not str(answer_text).strip():
        return 0.0
    if question.question_type == 'fill_blank':
        return _fill_blank_fraction(answer_text, question.correct_answer) or 0.0
    if question.question_type == 'matching':
        from .question_forms import matching_answer_key
        return _matching_fraction(answer_text, matching_answer_key(question.id, question.matching_pairs))
    return 0.0


@transaction.atomic
def auto_grade_attempt(student, exam):
    """پس از ثبت نهایی، پاسخ‌های عینی دانش‌آموز را نمره‌گذاری خودکار می‌کند.
    فقط پاسخ‌هایی که قبلاً نمره دستی نگرفته‌اند touched می‌شوند.
    شمارش نمره‌های خودکار برمی‌گردد."""
    from .models import Question, StudentAnswer

    graded = 0
    questions = {q.id: q for q in Question.objects.filter(exam=exam)}
    answers = StudentAnswer.objects.filter(student=student, question__in=list(questions.keys()))
    for answer in answers.select_for_update():
        question = questions.get(answer.question_id)
        if question is None or answer.graded_by_id is not None:
            continue  # نمره دستی معلم دست‌نخورده می‌ماند
        fraction = evaluate_fraction(question, answer.answer_text)
        if fraction is None:
            continue
        answer.score_obtained = round(float(question.max_score) * fraction, 2)
        answer.auto_graded = True
        answer.save(update_fields=['score_obtained', 'auto_graded', 'updated_at'])
        graded += 1
    return graded
