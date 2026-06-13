from locust import HttpUser, task, between
import random
import json


class StudentUser(HttpUser):
    """شبیه‌سازی دانش‌آموز"""
    wait_time = between(1, 3)

    username = "student1"
    password = "12345"

    def on_start(self):
        """ورود دانش‌آموز"""
        login_data = {'username': self.username, 'password': self.password}
        with self.client.post("/login/", data=login_data, catch_response=True) as response:
            if response.status_code in [200, 302]:
                print("✅ دانش‌آموز وارد شد")
                response.success()
            else:
                response.failure("Login failed")

    @task(3)
    def view_dashboard(self):
        """مشاهده داشبورد"""
        self.client.get("/student/dashboard/", name="[Student] Dashboard")

    @task(5)
    def take_exam(self):
        """شرکت در آزمون (بارگذاری صفحه)"""
        exam_id = 8  # آیدی آزمون مورد نظر
        self.client.get(f"/student/exam/{exam_id}/", name="[Student] Take Exam")

    @task(4)
    def save_answer(self):
        """ذخیره پاسخ"""
        answer_data = {
            'question_id': random.randint(1, 5),
            'answer_text': f'پاسخ تستی شماره {random.randint(1, 100)}'
        }
        self.client.post("/student/save-answer/",
                         json=answer_data,
                         name="[Student] Save Answer",
                         headers={'Content-Type': 'application/json'})
