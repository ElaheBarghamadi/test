"""تصحیح خودکار پاسخ‌های عینی (تستی/صحیح‌غلط/جاخالی/وصل‌کردنی) پس از ثبت نهایی آزمون."""
import json

from django.db import transaction


def _normalize_fa_text(value):
    """یکسان‌سازی متن فارسی برای مقایسه"""
    if value is None:
        return ''
    text = str(value).strip().lower()
    text = text.replace('\u200c', ' ').replace('\u064a', 'ی').replace('\u0643', 'ک').replace('\u0629', 'ه')
    return ' '.join(text.split())


def fill_blank_is_correct(answer_text, correct_answer):
    """مقایسه پاسخ جاخالی («مقدار۱ | مقدار۲») با پاسخ صحیح («مقدار۱, مقدار۲»)"""
    given = [_normalize_fa_text(p) for p in str(answer_text or '').split('|')]
    expected = [_normalize_fa_text(p) for p in str(correct_answer or '').replace('،', ',').split(',') if p.strip()]
    if not expected:
        return False
    if len(given) == 1 and len(expected) > 1:
        return given[0] == _normalize_fa_text(correct_answer)
    return all(i < len(given) and given[i] == want for i, want in enumerate(expected))


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
    for key, want in expected.items():
        if str(given.get(key, '')).strip() != str(want).strip():
            return False
    return True


AUTO_TYPES = ('true_false', 'multiple_choice', 'fill_blank', 'matching')


def evaluate_answer(question, answer_text):
    """True/False برای سوالات عینی؛ None یعنی نیاز به تصحیح دستی"""
    if question.question_type not in AUTO_TYPES:
        return None
    correct = (question.correct_answer or '').strip()
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
        verdict = evaluate_answer(question, answer.answer_text)
        if verdict is None:
            continue
        answer.score_obtained = float(question.max_score) if verdict else 0.0
        answer.auto_graded = True
        answer.save(update_fields=['score_obtained', 'auto_graded', 'updated_at'])
        graded += 1
    return graded
