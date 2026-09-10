# teacher_panel/import_export.py
# -*- coding: utf-8 -*-

import pandas as pd
from decimal import Decimal
from django.core.files.uploadedfile import UploadedFile
from exams.models import Question
from django.db.models import Max
import os
import tempfile


class QuestionExcelImporter:
    """کلاس مدیریت وارد کردن سوالات از اکسل"""

    REQUIRED_COLUMNS = ['text', 'question_type', 'max_score']

    TYPE_MAPPING = {
        'تستی': 'multiple_choice',
        'چهارگزینه‌ای': 'multiple_choice',
        'multiple_choice': 'multiple_choice',
        'صحیح/غلط': 'true_false',
        'true_false': 'true_false',
        'پاسخ کوتاه': 'short_answer',
        'short_answer': 'short_answer',
        'تشریحی': 'long_answer',
        'long_answer': 'long_answer',
        'وصل کردنی': 'matching',
        'matching': 'matching',
        'تصویری': 'image_answer',
        'image_answer': 'image_answer',
    }

    def __init__(self, exam):
        self.exam = exam
        self.errors = []
        self.warnings = []
        self.success_count = 0
        self.skip_count = 0

    def process_file(self, file_obj: UploadedFile):
        """پردازش فایل اکسل آپلود شده"""
        try:
            # خواندن فایل با pandas
            df = pd.read_excel(file_obj, index_col=False)
            # ⚠️ سلول‌های خالی باید None شوند؛ در غیر این صورت مقدار nan
            # (که truthy است) به‌عنوان متن سوال وارد و رشته «nan» ذخیره می‌شد.
            df = df.astype(object).where(pd.notnull(df), None)

            # بررسی وجود ستون‌های مورد نیاز
            df_columns = [str(col).strip() for col in df.columns]
            missing_cols = [col for col in self.REQUIRED_COLUMNS if col not in df_columns]
            if missing_cols:
                return {
                    'success': False,
                    'error': f'ستون‌های {", ".join(missing_cols)} در فایل وجود ندارند'
                }

            # پردازش هر ردیف
            for index, row in df.iterrows():
                self._process_row(index + 2, row)  # +2 چون شمارش از 1 شروع و هدر دارد

            return {
                'success': True,
                'success_count': self.success_count,
                'skip_count': self.skip_count,
                'errors': self.errors,
                'warnings': self.warnings
            }

        except Exception as e:
            return {'success': False, 'error': f'خطا در خواندن فایل: {str(e)}'}

    @staticmethod
    def _cell(row, column, default=None):
        """خواندن امن یک سلول: مقدار nan/خالی به default تبدیل می‌شود"""
        try:
            value = row.get(column)
        except Exception:
            return default
        if value is None:
            return default
        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass
        if isinstance(value, str) and not value.strip():
            return default
        return value

    def _process_row(self, row_num, row):
        """پردازش یک ردیف از اکسل"""
        try:
            # اعتبارسنجی فیلدهای اجباری
            text = self._cell(row, 'text')
            q_type_raw = self._cell(row, 'question_type')
            max_score_raw = self._cell(row, 'max_score')

            if not text:
                self.errors.append(f'ردیف {row_num}: متن سوال خالی است')
                self.skip_count += 1
                return

            if not q_type_raw:
                self.errors.append(f'ردیف {row_num}: نوع سوال مشخص نشده است')
                self.skip_count += 1
                return

            if not max_score_raw:
                self.errors.append(f'ردیف {row_num}: نمره سوال مشخص نشده است')
                self.skip_count += 1
                return

            # تبدیل نوع سوال
            q_type = self.TYPE_MAPPING.get(str(q_type_raw).strip().lower())
            if not q_type:
                self.errors.append(f'ردیف {row_num}: نوع سوال "{q_type_raw}" معتبر نیست')
                self.skip_count += 1
                return

            # اعتبارسنجی نمره
            try:
                max_score = Decimal(str(max_score_raw))
                if max_score <= 0:
                    raise ValueError
                max_score = round(max_score, 2)
            except:
                self.errors.append(f'ردیف {row_num}: نمره "{max_score_raw}" معتبر نیست')
                self.skip_count += 1
                return

            # ایجاد سوال
            question = Question(
                exam=self.exam,
                text=str(text)[:5000],
                question_type=q_type,
                max_score=max_score,
                # بزرگ‌ترین order موجود + ۱ (قبلاً count() + success_count بود
                # و شماره‌ها ۱،۳،۵,... می‌شدند)
                order=(self.exam.questions.aggregate(m=Max('order'))['m'] or 0) + 1,
                allow_image_answer=str(self._cell(row, 'allow_image_answer', '')).strip().lower()
                in ('true', '1', 'yes', 'بله')
            )

            # تنظیم فیلدهای اختصاصی بر اساس نوع سوال
            self._set_question_fields(question, row, q_type)

            question.save()
            self.success_count += 1

        except Exception as e:
            self.errors.append(f'ردیف {row_num}: خطای سیستمی - {str(e)}')
            self.skip_count += 1

    def _set_question_fields(self, question, row, q_type):
        """تنظیم فیلدهای اختصاصی سوال"""

        # تنظیم گزینه‌ها برای سوالات تستی
        if q_type == 'multiple_choice':
            options = []
            for i in range(1, 5):
                opt = self._cell(row, f'option_{i}')
                if opt and str(opt).strip():
                    options.append(str(opt).strip())
                else:
                    options.append(f"گزینه {i}")
            question.options = options
            options_type = str(self._cell(row, 'options_type', 'text')).strip()
            question.options_type = options_type if options_type in ('text', 'image', 'mixed') else 'text'

            # پاسخ صحیح
            correct = self._cell(row, 'correct_answer', '1')
            if correct in ['1', '2', '3', '4']:
                question.correct_answer = str(correct)
            else:
                question.correct_answer = '1'
                self.warnings.append(f'سوال "{question.text[:30]}..." پاسخ صحیح نامعتبر، گزینه 1 تنظیم شد')

        # صحیح/غلط
        elif q_type == 'true_false':
            correct = str(self._cell(row, 'correct_answer', '')).lower().strip()
            if correct in ['true', 'صحیح', '✅', '1']:
                question.correct_answer = 'true'
            elif correct in ['false', 'غلط', '❌', '0']:
                question.correct_answer = 'false'
            else:
                question.correct_answer = 'true'
                self.warnings.append(f'سوال "{question.text[:30]}..." پاسخ صحیح نامعتبر، "صحیح" تنظیم شد')

        # پاسخ کوتاه/تشریحی
        elif q_type in ['short_answer', 'long_answer']:
            correct = self._cell(row, 'correct_answer')
            if correct:
                question.correct_answer = str(correct)

        # وصل کردنی
        elif q_type == 'matching':
            pairs_str = self._cell(row, 'matching_pairs', '')
            pairs = []
            if pairs_str:
                for pair in str(pairs_str).split(';'):
                    parts = pair.split(',')
                    if len(parts) == 2:
                        pairs.append({
                            'left': parts[0].strip(),
                            'right': parts[1].strip()
                        })
            question.matching_pairs = pairs

        # تنظیم تصویر سوال
        image_url = self._cell(row, 'image_url')
        # توجه: برای آپلود واقعی تصویر نیاز به پردازش جداگانه دارد


class QuestionExcelExporter:
    """کلاس ساخت فایل اکسل نمونه برای دانلود"""

    @staticmethod
    def create_template():
        """ایجاد فایل اکسل نمونه"""
        data = {
            'text': ['متن سوال را در اینجا وارد کنید'],
            'question_type': ['تستی'],
            'max_score': [1.0],
            'option_1': ['گزینه اول'],
            'option_2': ['گزینه دوم'],
            'option_3': ['گزینه سوم'],
            'option_4': ['گزینه چهارم'],
            'correct_answer': ['1'],
            'allow_image_answer': [False],
            'options_type': ['text'],
            'matching_pairs': ['left1,right1;left2,right2'],
            'image_url': ['optional/path/to/image.jpg']
        }

        df = pd.DataFrame(data)

        # ایجاد فایل موقت
        with tempfile.NamedTemporaryFile(suffix='.xlsx', delete=False) as tmp:
            output_path = tmp.name

        # نوشتن فایل
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='Questions', index=False)

            # اضافه کردن sheet راهنما
            help_data = {
                'ستون': ['text', 'question_type', 'max_score', 'option_1', 'option_2', 'option_3', 'option_4',
                         'correct_answer', 'allow_image_answer', 'options_type', 'matching_pairs', 'image_url'],
                'توضیحات': [
                    'متن سوال (اجباری)',
                    'نوع سوال: تستی | صحیح/غلط | پاسخ کوتاه | تشریحی | وصل کردنی | تصویری',
                    'نمره سوال (اجباری - عدد اعشاری مثل 1.5)',
                    'گزینه 1 (فقط برای سوالات تستی)',
                    'گزینه 2 (فقط برای سوالات تستی)',
                    'گزینه 3 (فقط برای سوالات تستی)',
                    'گزینه 4 (فقط برای سوالات تستی)',
                    'پاسخ صحیح (تستی: شماره گزینه 1-4، صحیح/غلط: true/false)',
                    'True/False - آیا دانش‌آموز می‌تواند عکس آپلود کند؟',
                    'نوع نمایش گزینه‌ها: text | image | mixed',
                    'برای سوالات وصل کردنی: left1,right1;left2,right2',
                    'آدرس تصویر سوال (اختیاری)'
                ]
            }
            help_df = pd.DataFrame(help_data)
            help_df.to_excel(writer, sheet_name='راهنما', index=False)

        return output_path