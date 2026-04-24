import csv
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import date, datetime, time
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal
from urllib import request
from urllib.error import URLError
from uuid import uuid4

from fastapi import FastAPI, File, Form, Header, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, HttpUrl

BASE_DIR = Path(__file__).resolve().parent
UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(exist_ok=True)

DEFAULT_ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
]


def parse_allowed_origins(value: str | None) -> list[str]:
    if not value:
        return DEFAULT_ALLOWED_ORIGINS

    origins = [item.strip() for item in value.split(",") if item.strip()]
    return origins or DEFAULT_ALLOWED_ORIGINS


app = FastAPI(
    title="Programming Pathshala Club API",
    description="Backend API for the programming club learning portal.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=parse_allowed_origins(os.getenv("APP_CORS_ORIGINS")),
    allow_origin_regex=os.getenv("APP_CORS_ORIGIN_REGEX"),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

ADMIN_EMAIL = "admin@pathshala.com"
ADMIN_PASSWORD = "admin123"
ADMIN_TOKEN = "pp-admin-demo-token"
ALLOWED_UPLOAD_EXTENSIONS = {".pdf", ".doc", ".docx", ".png", ".jpg", ".jpeg", ".webp"}
MAX_UPLOAD_SIZE_BYTES = 8 * 1024 * 1024

ApplicationStatus = Literal[
    "applied",
    "under_review",
    "shortlisted",
    "interview_scheduled",
    "selected",
    "rejected",
]


class AdminLogin(BaseModel):
    email: str
    password: str


class StudentRegister(BaseModel):
    name: str
    email: str
    password: str
    phone: str = ""
    college: str = ""
    course: str = ""
    graduation_year: str = ""
    skills: list[str] = []


class StudentLogin(BaseModel):
    email: str
    password: str


class Student(BaseModel):
    id: int
    name: str
    email: str
    password_hash: str
    phone: str = ""
    college: str = ""
    course: str = ""
    graduation_year: str = ""
    skills: list[str] = []
    created_at: datetime


class StudentPublic(BaseModel):
    id: int
    name: str
    email: str
    phone: str = ""
    college: str = ""
    course: str = ""
    graduation_year: str = ""
    skills: list[str] = []
    created_at: datetime


class StudentResume(BaseModel):
    student_id: int = 0
    name: str = ""
    role: str = ""
    email: str = ""
    phone: str = ""
    links: str = ""
    summary: str = ""
    education: str = ""
    skills: str = ""
    projects: str = ""
    experience: str = ""
    achievements: str = ""
    certifications: str = ""
    updated_at: datetime = Field(default_factory=datetime.now)


class JobBase(BaseModel):
    title: str
    company: str
    location: str
    job_type: str
    skills: list[str]
    description: str
    eligibility: str
    compensation: str
    last_date: date
    apply_link: HttpUrl
    attachment_name: str | None = None
    attachment_url: str | None = None


class Job(JobBase):
    id: int


class JobApplication(BaseModel):
    id: int
    student_id: int
    job_id: int
    status: ApplicationStatus = "applied"
    admin_note: str = ""
    ats_score: int | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    ai_suggestions: list[str] = Field(default_factory=list)
    applied_with_ai_fix: bool = False
    applied_at: datetime
    updated_at: datetime


class ResumeCheckResult(BaseModel):
    score: int
    verdict: str
    can_apply: bool
    matched_keywords: list[str]
    missing_keywords: list[str]
    weak_sections: list[str]
    suggestions: list[str]
    suggested_resume_patch: dict[str, str]


class JobApplyRequest(BaseModel):
    ats_score: int | None = None
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    ai_suggestions: list[str] = Field(default_factory=list)
    applied_with_ai_fix: bool = False


class ResumePatchRequest(BaseModel):
    patch: dict[str, str]


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus
    admin_note: str = ""


class EventBase(BaseModel):
    title: str
    event_date: date
    event_time: time
    mode: str
    description: str
    speaker: str
    registration_link: HttpUrl
    event_kind: Literal["standard", "coding_assessment"] = "standard"
    coding_assessment_id: int | None = None
    attachment_name: str | None = None
    attachment_url: str | None = None


class Event(EventBase):
    id: int


CodingLanguage = Literal["python", "cpp"]


class CodingQuestion(BaseModel):
    id: int
    title: str
    prompt: str
    difficulty: Literal["easy", "medium", "hard"]
    topic: str
    language: CodingLanguage = "python"
    languages: list[CodingLanguage] = Field(default_factory=lambda: ["python", "cpp"])
    function_name: str
    signature: str
    starter_code: str
    signatures: dict[str, str] = Field(default_factory=dict)
    starter_codes: dict[str, str] = Field(default_factory=dict)
    examples: list[str] = Field(default_factory=list)
    hidden_tests: list[dict[str, Any]] = Field(default_factory=list)


class CodingAssessment(BaseModel):
    id: int
    title: str
    description: str
    duration_minutes: int
    question_count: int = 3
    question_pool_ids: list[int] = Field(default_factory=list)


CodingVerdict = Literal["pending", "accepted", "partial", "failed", "runtime_error", "syntax_error"]


class CodingAttemptQuestionResult(BaseModel):
    question_id: int
    language: CodingLanguage = "python"
    code: str = ""
    passed_tests: int = 0
    total_tests: int = 0
    score: int = 0
    verdict: CodingVerdict = "pending"
    feedback: str = ""
    last_submitted_at: datetime | None = None


class CodingAttempt(BaseModel):
    id: int
    student_id: int
    assessment_id: int
    selected_question_ids: list[int] = Field(default_factory=list)
    question_results: list[CodingAttemptQuestionResult] = Field(default_factory=list)
    status: Literal["in_progress", "submitted"] = "in_progress"
    total_score: int = 0
    solved_count: int = 0
    started_at: datetime
    submitted_at: datetime | None = None


class CodingSubmissionRequest(BaseModel):
    code: str
    language: CodingLanguage = "python"


class InterviewRequest(BaseModel):
    skills: list[str]
    role: str = "Software Developer"
    round_type: Literal["technical", "hr", "mixed"] = "mixed"
    difficulty: Literal["beginner", "intermediate", "advanced"] = "intermediate"


class InterviewAnswer(BaseModel):
    question: str
    answer: str
    skills: list[str]


class InterviewSessionReply(BaseModel):
    session_id: str
    answer: str


class MockInterviewAttempt(BaseModel):
    id: int
    student_id: int
    role: str
    round_type: str
    skills: list[str]
    question: str
    answer: str
    score: int
    strength: str
    suggestions: list[str]
    sample_answer: str
    created_at: datetime


class ClassSchedule(BaseModel):
    id: int
    class_date: date
    title: str
    mentor: str
    starts_at: time
    link: str


jobs: list[Job] = [
    Job(
        id=1,
        title="Frontend Developer Intern",
        company="CodeCraft Labs",
        location="Remote",
        job_type="Internship",
        skills=["React", "TypeScript", "CSS"],
        description="Build responsive UI screens, fix accessibility issues, and ship small product improvements.",
        eligibility="Students with at least two frontend projects or a strong GitHub portfolio.",
        compensation="Rs. 12,000/month stipend",
        last_date=date(2026, 5, 15),
        apply_link="https://example.com/apply/frontend-intern",
    ),
    Job(
        id=2,
        title="Python Automation Trainee",
        company="DataNest Solutions",
        location="Bengaluru",
        job_type="Full time trainee",
        skills=["Python", "APIs", "SQL"],
        description="Create scripts, clean data, connect APIs, and document repeatable automation workflows.",
        eligibility="Comfortable with Python basics, functions, files, and simple database queries.",
        compensation="Rs. 4.2 LPA",
        last_date=date(2026, 5, 22),
        apply_link="https://example.com/apply/python-trainee",
    ),
]

events: list[Event] = [
    Event(
        id=1,
        title="Resume Review Sprint",
        event_date=date(2026, 5, 4),
        event_time=time(17, 30),
        mode="Online",
        description="Bring one resume draft and leave with sharper bullets, project framing, and cleaner structure.",
        speaker="Placement Cell Mentors",
        registration_link="https://example.com/events/resume-review",
    ),
    Event(
        id=2,
        title="DSA Interview Jam",
        event_date=date(2026, 5, 9),
        event_time=time(10, 0),
        mode="Lab 2",
        description="Practice arrays, hashing, and two-pointer patterns with peer review after every round.",
        speaker="Programming Pathshala Club",
        registration_link="https://example.com/events/dsa-jam",
    ),
    Event(
        id=3,
        title="Coding Evaluation Arena",
        event_date=date(2026, 5, 18),
        event_time=time(14, 0),
        mode="Assessment room",
        description="Take a timed coding evaluation with three random questions and store your result in the student dashboard.",
        speaker="Placement Tech Panel",
        registration_link="https://example.com/events/coding-evaluation-arena",
        event_kind="coding_assessment",
        coding_assessment_id=1,
    ),
]

coding_questions: list[CodingQuestion] = [
    CodingQuestion(
        id=1,
        title="Running Sum Array",
        prompt="Write a function that returns the running sum of an integer array. Each position should contain the sum of every value from index 0 through that position.",
        difficulty="easy",
        topic="Arrays",
        function_name="running_sum",
        signature="def running_sum(nums: list[int]) -> list[int]:",
        starter_code="""def running_sum(nums: list[int]) -> list[int]:
    # Return the running sum for the array.
    pass
""",
        signatures={
            "python": "def running_sum(nums: list[int]) -> list[int]:",
            "cpp": "vector<int> running_sum(vector<int> nums)",
        },
        starter_codes={
            "python": """def running_sum(nums: list[int]) -> list[int]:
    # Return the running sum for the array.
    pass
""",
            "cpp": """vector<int> running_sum(vector<int> nums) {
    // Return the running sum for the array.
    return {};
}
""",
        },
        examples=[
            "running_sum([1, 2, 3, 4]) -> [1, 3, 6, 10]",
            "running_sum([3, 1, 2, 10, 1]) -> [3, 4, 6, 16, 17]",
        ],
        hidden_tests=[
            {"args": [[1, 2, 3, 4]], "expected": [1, 3, 6, 10]},
            {"args": [[3, 1, 2, 10, 1]], "expected": [3, 4, 6, 16, 17]},
            {"args": [[7]], "expected": [7]},
            {"args": [[-1, 5, 2]], "expected": [-1, 4, 6]},
        ],
    ),
    CodingQuestion(
        id=2,
        title="First Unique Character",
        prompt="Return the index of the first non-repeating character in a string. Return -1 if every character repeats.",
        difficulty="easy",
        topic="Strings",
        function_name="first_unique_char",
        signature="def first_unique_char(text: str) -> int:",
        starter_code="""def first_unique_char(text: str) -> int:
    # Return the index of the first unique character or -1.
    pass
""",
        signatures={
            "python": "def first_unique_char(text: str) -> int:",
            "cpp": "int first_unique_char(string text)",
        },
        starter_codes={
            "python": """def first_unique_char(text: str) -> int:
    # Return the index of the first unique character or -1.
    pass
""",
            "cpp": """int first_unique_char(string text) {
    // Return the index of the first unique character or -1.
    return -1;
}
""",
        },
        examples=[
            "first_unique_char('leetcode') -> 0",
            "first_unique_char('aabb') -> -1",
        ],
        hidden_tests=[
            {"args": ["leetcode"], "expected": 0},
            {"args": ["loveleetcode"], "expected": 2},
            {"args": ["aabb"], "expected": -1},
            {"args": ["z"], "expected": 0},
        ],
    ),
    CodingQuestion(
        id=3,
        title="Best Time To Buy And Sell Stock",
        prompt="Given a list of stock prices where each price is for one day, return the maximum profit you can achieve with exactly one buy and one sell. If no profit is possible, return 0.",
        difficulty="easy",
        topic="Arrays",
        function_name="max_profit",
        signature="def max_profit(prices: list[int]) -> int:",
        starter_code="""def max_profit(prices: list[int]) -> int:
    # Return the best profit possible from one buy and one sell.
    pass
""",
        signatures={
            "python": "def max_profit(prices: list[int]) -> int:",
            "cpp": "int max_profit(vector<int> prices)",
        },
        starter_codes={
            "python": """def max_profit(prices: list[int]) -> int:
    # Return the best profit possible from one buy and one sell.
    pass
""",
            "cpp": """int max_profit(vector<int> prices) {
    // Return the best profit possible from one buy and one sell.
    return 0;
}
""",
        },
        examples=[
            "max_profit([7, 1, 5, 3, 6, 4]) -> 5",
            "max_profit([7, 6, 4, 3, 1]) -> 0",
        ],
        hidden_tests=[
            {"args": [[7, 1, 5, 3, 6, 4]], "expected": 5},
            {"args": [[7, 6, 4, 3, 1]], "expected": 0},
            {"args": [[2, 4, 1]], "expected": 2},
            {"args": [[3, 2, 6, 5, 0, 3]], "expected": 4},
        ],
    ),
    CodingQuestion(
        id=4,
        title="Merge Overlapping Ranges",
        prompt="Merge all overlapping intervals and return the final set sorted by starting value.",
        difficulty="medium",
        topic="Intervals",
        function_name="merge_ranges",
        signature="def merge_ranges(intervals: list[list[int]]) -> list[list[int]]:",
        starter_code="""def merge_ranges(intervals: list[list[int]]) -> list[list[int]]:
    # Merge overlapping intervals and return them sorted.
    pass
""",
        signatures={
            "python": "def merge_ranges(intervals: list[list[int]]) -> list[list[int]]:",
            "cpp": "vector<vector<int>> merge_ranges(vector<vector<int>> intervals)",
        },
        starter_codes={
            "python": """def merge_ranges(intervals: list[list[int]]) -> list[list[int]]:
    # Merge overlapping intervals and return them sorted.
    pass
""",
            "cpp": """vector<vector<int>> merge_ranges(vector<vector<int>> intervals) {
    // Merge overlapping intervals and return them sorted.
    return {};
}
""",
        },
        examples=[
            "merge_ranges([[1, 3], [2, 6], [8, 10], [15, 18]]) -> [[1, 6], [8, 10], [15, 18]]",
            "merge_ranges([[1, 4], [4, 5]]) -> [[1, 5]]",
        ],
        hidden_tests=[
            {"args": [[[1, 3], [2, 6], [8, 10], [15, 18]]], "expected": [[1, 6], [8, 10], [15, 18]]},
            {"args": [[[1, 4], [4, 5]]], "expected": [[1, 5]]},
            {"args": [[[5, 7], [1, 2], [2, 4]]], "expected": [[1, 4], [5, 7]]},
            {"args": [[[1, 5]]], "expected": [[1, 5]]},
        ],
    ),
    CodingQuestion(
        id=5,
        title="Rotate Words",
        prompt="Rotate the words in a sentence to the right by the given number of steps. Words should stay separated by a single space in the final answer.",
        difficulty="medium",
        topic="Strings",
        function_name="rotate_words",
        signature="def rotate_words(sentence: str, steps: int) -> str:",
        starter_code="""def rotate_words(sentence: str, steps: int) -> str:
    # Rotate the words in the sentence to the right.
    pass
""",
        signatures={
            "python": "def rotate_words(sentence: str, steps: int) -> str:",
            "cpp": "string rotate_words(string sentence, int steps)",
        },
        starter_codes={
            "python": """def rotate_words(sentence: str, steps: int) -> str:
    # Rotate the words in the sentence to the right.
    pass
""",
            "cpp": """string rotate_words(string sentence, int steps) {
    // Rotate the words in the sentence to the right.
    return sentence;
}
""",
        },
        examples=[
            "rotate_words('code every single day', 1) -> 'day code every single'",
            "rotate_words('plan build ship', 2) -> 'build ship plan'",
        ],
        hidden_tests=[
            {"args": ["code every single day", 1], "expected": "day code every single"},
            {"args": ["plan build ship", 2], "expected": "build ship plan"},
            {"args": ["keep going", 3], "expected": "going keep"},
            {"args": ["solo", 5], "expected": "solo"},
        ],
    ),
]

coding_assessments: list[CodingAssessment] = [
    CodingAssessment(
        id=1,
        title="Placement Coding Evaluation",
        description="Three random coding questions with Python and C++ support, scored and saved to the student dashboard.",
        duration_minutes=75,
        question_count=3,
        question_pool_ids=[question.id for question in coding_questions],
    )
]

classes: list[ClassSchedule] = [
    ClassSchedule(
        id=1,
        class_date=date(2026, 5, 6),
        title="React state and forms",
        mentor="Aditi Sharma",
        starts_at=time(16, 0),
        link="Will be shared soon",
    ),
    ClassSchedule(
        id=2,
        class_date=date(2026, 5, 8),
        title="SQL joins practice",
        mentor="Rahul Verma",
        starts_at=time(15, 30),
        link="Will be shared soon",
    ),
]

students: list[Student] = [
    Student(
        id=1,
        name="Raj Student",
        email="raj@example.com",
        password_hash=sha256("student123".encode()).hexdigest(),
        phone="+91 98765 43210",
        college="ABC Institute of Technology",
        course="B.Tech Computer Science",
        graduation_year="2026",
        skills=["React", "TypeScript", "SQL"],
        created_at=datetime.now(),
    )
]

student_tokens: dict[str, int] = {}

student_resumes: dict[int, StudentResume] = {
    1: StudentResume(
        student_id=1,
        name="Raj Student",
        role="Frontend Developer",
        email="raj@example.com",
        phone="+91 98765 43210",
        links="linkedin.com/in/raj | github.com/raj",
        summary="Computer Science student seeking a fresher software role with strong foundations in frontend development, APIs, SQL, and problem solving.",
        education="B.Tech Computer Science, 2026 - ABC Institute of Technology, CGPA: 8.4/10\nClass XII - Science Stream, 2022, 86%",
        skills="React, TypeScript, JavaScript, Python, SQL, HTML, CSS, Git",
        projects="Placement Portal - Built job listing and resume builder screens using Next.js.\nAPI Tracker - Created a FastAPI service for tracking study tasks.",
        experience="Frontend Intern - Improved reusable components and fixed responsive layout bugs.",
        achievements="Solved 250+ DSA problems across arrays, strings, trees, and dynamic programming.\nLed a team of 4 for a college hackathon prototype.",
        certifications="Python Basics Certificate\nWeb Development Bootcamp",
        updated_at=datetime.now(),
    )
}

job_applications: list[JobApplication] = [
    JobApplication(
        id=1,
        student_id=1,
        job_id=1,
        status="under_review",
        admin_note="Resume looks relevant. Review project links before shortlisting.",
        applied_at=datetime.now(),
        updated_at=datetime.now(),
    )
]

mock_attempts: list[MockInterviewAttempt] = []
coding_attempts: list[CodingAttempt] = []
interview_sessions: dict[str, dict[str, object]] = {}


def public_student(student: Student) -> StudentPublic:
    return StudentPublic(**student.model_dump(exclude={"password_hash"}))


def hash_password(password: str) -> str:
    return sha256(password.encode()).hexdigest()


def find_student_by_email(email: str) -> Student | None:
    return next((student for student in students if student.email.lower() == email.lower()), None)


def find_job(job_id: int) -> Job:
    job = next((item for item in jobs if item.id == job_id), None)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


def find_coding_question(question_id: int) -> CodingQuestion:
    question = next((item for item in coding_questions if item.id == question_id), None)
    if question is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding question not found.")
    return question


def find_coding_assessment(assessment_id: int) -> CodingAssessment:
    assessment = next((item for item in coding_assessments if item.id == assessment_id), None)
    if assessment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding assessment not found.")
    return assessment


def public_coding_question(question: CodingQuestion) -> dict[str, object]:
    return {
        "id": question.id,
        "title": question.title,
        "prompt": question.prompt,
        "difficulty": question.difficulty,
        "topic": question.topic,
        "language": question.language,
        "languages": question.languages,
        "function_name": question.function_name,
        "signature": question.signature,
        "starter_code": question.starter_code,
        "signatures": question.signatures or {question.language: question.signature},
        "starter_codes": question.starter_codes or {question.language: question.starter_code},
        "examples": question.examples,
    }


def coding_attempt_result(attempt: CodingAttempt, question_id: int) -> CodingAttemptQuestionResult:
    result = next((item for item in attempt.question_results if item.question_id == question_id), None)
    if result is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question result not found.")
    return result


def recalculate_coding_attempt(attempt: CodingAttempt) -> CodingAttempt:
    total_results = len(attempt.question_results)
    if not total_results:
        return attempt.model_copy(update={"total_score": 0, "solved_count": 0})
    total_score = round(sum(result.score for result in attempt.question_results) / total_results)
    solved_count = sum(1 for result in attempt.question_results if result.verdict == "accepted")
    return attempt.model_copy(update={"total_score": total_score, "solved_count": solved_count})


def coding_attempt_summary(attempt: CodingAttempt) -> dict[str, object]:
    assessment = find_coding_assessment(attempt.assessment_id)
    return {
        "id": attempt.id,
        "assessment_id": assessment.id,
        "assessment_title": assessment.title,
        "status": attempt.status,
        "total_score": attempt.total_score,
        "solved_count": attempt.solved_count,
        "question_count": len(attempt.selected_question_ids),
        "started_at": attempt.started_at,
        "submitted_at": attempt.submitted_at,
    }


def coding_attempt_payload(attempt: CodingAttempt) -> dict[str, object]:
    assessment = find_coding_assessment(attempt.assessment_id)
    questions_payload = []
    for question_id in attempt.selected_question_ids:
        question = find_coding_question(question_id)
        result = coding_attempt_result(attempt, question_id)
        questions_payload.append({**public_coding_question(question), "result": result.model_dump()})
    return {
        "id": attempt.id,
        "status": attempt.status,
        "total_score": attempt.total_score,
        "solved_count": attempt.solved_count,
        "started_at": attempt.started_at,
        "submitted_at": attempt.submitted_at,
        "assessment": {
            "id": assessment.id,
            "title": assessment.title,
            "description": assessment.description,
            "duration_minutes": assessment.duration_minutes,
            "question_count": assessment.question_count,
        },
        "questions": questions_payload,
    }


def cpp_compiler_path() -> str | None:
    return os.getenv("CPP_COMPILER") or shutil.which("g++") or shutil.which("clang++")


def cpp_int_vector(values: list[int]) -> str:
    return "{" + ", ".join(str(value) for value in values) + "}"


def cpp_int_matrix(values: list[list[int]]) -> str:
    return "{" + ", ".join(cpp_int_vector(row) for row in values) + "}"


def cpp_string_literal(value: str) -> str:
    return json.dumps(value)


def build_cpp_runner(question: CodingQuestion, candidate_path: Path) -> str:
    if question.id == 1:
        tests = ",\n".join(
            f"        {{{cpp_int_vector(test['args'][0])}, {cpp_int_vector(test['expected'])}}}"
            for test in question.hidden_tests
        )
        runner_body = "\n".join(
            [
                "    vector<pair<vector<int>, vector<int>>> tests = {",
                tests,
                "    };",
                "    int passed = 0;",
                "    int total = static_cast<int>(tests.size());",
                "    for (const auto& test : tests) {",
                f"        auto output = {question.function_name}(test.first);",
                "        if (output == test.second) {",
                "            passed++;",
                "        }",
                "    }",
                '    cout << passed << "/" << total;',
            ]
        )
    elif question.id == 2:
        tests = ",\n".join(
            f"        {{{cpp_string_literal(test['args'][0])}, {test['expected']}}}"
            for test in question.hidden_tests
        )
        runner_body = "\n".join(
            [
                "    vector<pair<string, int>> tests = {",
                tests,
                "    };",
                "    int passed = 0;",
                "    int total = static_cast<int>(tests.size());",
                "    for (const auto& test : tests) {",
                f"        auto output = {question.function_name}(test.first);",
                "        if (output == test.second) {",
                "            passed++;",
                "        }",
                "    }",
                '    cout << passed << "/" << total;',
            ]
        )
    elif question.id == 3:
        tests = ",\n".join(
            f"        {{{cpp_int_vector(test['args'][0])}, {test['expected']}}}"
            for test in question.hidden_tests
        )
        runner_body = "\n".join(
            [
                "    vector<pair<vector<int>, int>> tests = {",
                tests,
                "    };",
                "    int passed = 0;",
                "    int total = static_cast<int>(tests.size());",
                "    for (const auto& test : tests) {",
                f"        auto output = {question.function_name}(test.first);",
                "        if (output == test.second) {",
                "            passed++;",
                "        }",
                "    }",
                '    cout << passed << "/" << total;',
            ]
        )
    elif question.id == 4:
        tests = ",\n".join(
            f"        {{{cpp_int_matrix(test['args'][0])}, {cpp_int_matrix(test['expected'])}}}"
            for test in question.hidden_tests
        )
        runner_body = "\n".join(
            [
                "    vector<pair<vector<vector<int>>, vector<vector<int>>>> tests = {",
                tests,
                "    };",
                "    int passed = 0;",
                "    int total = static_cast<int>(tests.size());",
                "    for (const auto& test : tests) {",
                f"        auto output = {question.function_name}(test.first);",
                "        if (output == test.second) {",
                "            passed++;",
                "        }",
                "    }",
                '    cout << passed << "/" << total;',
            ]
        )
    elif question.id == 5:
        tests = ",\n".join(
            f"        {{{cpp_string_literal(test['args'][0])}, {test['args'][1]}, {cpp_string_literal(test['expected'])}}}"
            for test in question.hidden_tests
        )
        runner_body = "\n".join(
            [
                "    struct TestCase { string sentence; int steps; string expected; };",
                "    vector<TestCase> tests = {",
                tests,
                "    };",
                "    int passed = 0;",
                "    int total = static_cast<int>(tests.size());",
                "    for (const auto& test : tests) {",
                f"        auto output = {question.function_name}(test.sentence, test.steps);",
                "        if (output == test.expected) {",
                "            passed++;",
                "        }",
                "    }",
                '    cout << passed << "/" << total;',
            ]
        )
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This question does not have a C++ harness yet.")

    return "\n".join(
        [
            "#include <bits/stdc++.h>",
            "using namespace std;",
            f'#include "{candidate_path.name}"',
            "",
            "int main() {",
            "    try {",
            runner_body,
            "    } catch (const exception& ex) {",
            "        cerr << ex.what();",
            "        return 2;",
            "    } catch (...) {",
            '        cerr << "Unknown runtime error";',
            "        return 2;",
            "    }",
            "    return 0;",
            "}",
        ]
    )


def evaluate_python_submission(question: CodingQuestion, code: str) -> dict[str, object]:
    clean_code = code.strip()
    if not clean_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Write some code before submitting.")

    runner_payload = json.dumps(question.hidden_tests)
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        candidate_path = tmp_path / "candidate.py"
        runner_path = tmp_path / "runner.py"
        candidate_path.write_text(code, encoding="utf-8")
        runner_path.write_text(
            "\n".join(
                [
                    "import json",
                    "import traceback",
                    f"candidate_source = {code!r}",
                    f"candidate_filename = {str(candidate_path)!r}",
                    f"tests = json.loads({runner_payload!r})",
                    "namespace = {}",
                    "try:",
                    "    exec(compile(candidate_source, candidate_filename, 'exec'), namespace)",
                    "except Exception:",
                    "    print(json.dumps({'status': 'load_error', 'error': traceback.format_exc()}))",
                    "    raise SystemExit(0)",
                    f"func = namespace.get('{question.function_name}')",
                    "if not callable(func):",
                    "    print(json.dumps({'status': 'missing_function'}))",
                    "    raise SystemExit(0)",
                    "results = []",
                    "for test in tests:",
                    "    try:",
                    "        args = test.get('args', [])",
                    "        kwargs = test.get('kwargs', {})",
                    "        output = func(*args, **kwargs)",
                    "        expected = test.get('expected')",
                    "        results.append({'passed': output == expected, 'output': output, 'expected': expected})",
                    "    except Exception:",
                    "        results.append({'passed': False, 'error': traceback.format_exc()})",
                    "print(json.dumps({'status': 'ok', 'results': results}))",
                ]
            ),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [sys.executable, str(runner_path)],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return {
                "passed_tests": 0,
                "total_tests": len(question.hidden_tests),
                "score": 0,
                "verdict": "runtime_error",
                "feedback": "The code timed out. Check loops, recursion, and exit conditions.",
            }

    stdout_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    stderr_text = completed.stderr.strip()
    if completed.returncode != 0 and not stdout_lines:
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "runtime_error",
            "feedback": "The evaluator failed before the tests could run."
            + (f" Details: {stderr_text.splitlines()[-1][:180]}" if stderr_text else ""),
        }
    if not stdout_lines:
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "runtime_error",
            "feedback": "The evaluator could not read a valid result from the submission.",
        }

    try:
        payload = json.loads(stdout_lines[-1])
    except json.JSONDecodeError:
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "runtime_error",
            "feedback": "The submission printed unexpected output while being evaluated.",
        }

    if payload.get("status") == "missing_function":
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "failed",
            "feedback": f"Define the required function exactly as `{question.function_name}`.",
        }

    if payload.get("status") == "load_error":
        error_text = str(payload.get("error", ""))
        verdict: CodingVerdict = "syntax_error" if "SyntaxError" in error_text else "runtime_error"
        friendly = "There is a syntax issue in the solution." if verdict == "syntax_error" else "The code raised an error before the tests could run."
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": verdict,
            "feedback": friendly,
        }

    results = payload.get("results", [])
    if not isinstance(results, list):
        results = []
    passed_tests = sum(1 for item in results if isinstance(item, dict) and item.get("passed"))
    total_tests = len(question.hidden_tests)
    score = round((passed_tests / max(total_tests, 1)) * 100)
    if passed_tests == total_tests:
        verdict = "accepted"
        feedback = "Strong solve. All hidden tests passed."
    elif passed_tests > 0:
        verdict = "partial"
        feedback = f"{passed_tests} of {total_tests} hidden tests passed. Check edge cases and return values."
    else:
        verdict = "failed"
        feedback = "No hidden tests passed yet. Recheck the approach and compare it with the examples."
    return {
        "passed_tests": passed_tests,
        "total_tests": total_tests,
        "score": score,
        "verdict": verdict,
        "feedback": feedback,
    }


def evaluate_cpp_submission(question: CodingQuestion, code: str) -> dict[str, object]:
    clean_code = code.strip()
    if not clean_code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Write some code before submitting.")

    compiler = cpp_compiler_path()
    if not compiler:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="C++ compiler is not available on the server.")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        candidate_path = tmp_path / "candidate.cpp"
        runner_path = tmp_path / "runner.cpp"
        executable_path = tmp_path / "runner.exe"
        candidate_path.write_text(code, encoding="utf-8")
        runner_path.write_text(build_cpp_runner(question, candidate_path), encoding="utf-8")

        try:
            compile_result = subprocess.run(
                [compiler, "-std=c++17", str(runner_path), "-o", str(executable_path)],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
                cwd=str(tmp_path),
            )
        except subprocess.TimeoutExpired:
            return {
                "passed_tests": 0,
                "total_tests": len(question.hidden_tests),
                "score": 0,
                "verdict": "runtime_error",
                "feedback": "The C++ compilation timed out.",
            }

        if compile_result.returncode != 0:
            compile_error = (compile_result.stderr or compile_result.stdout).strip()
            last_line = compile_error.splitlines()[-1][:220] if compile_error else ""
            return {
                "passed_tests": 0,
                "total_tests": len(question.hidden_tests),
                "score": 0,
                "verdict": "syntax_error",
                "feedback": "The C++ code did not compile." + (f" Details: {last_line}" if last_line else ""),
            }

        try:
            run_result = subprocess.run(
                [str(executable_path)],
                capture_output=True,
                text=True,
                timeout=4,
                check=False,
                cwd=str(tmp_path),
            )
        except subprocess.TimeoutExpired:
            return {
                "passed_tests": 0,
                "total_tests": len(question.hidden_tests),
                "score": 0,
                "verdict": "runtime_error",
                "feedback": "The C++ code timed out. Check loops and edge cases.",
            }

    stdout = run_result.stdout.strip()
    stderr = run_result.stderr.strip()
    if run_result.returncode != 0 and not stdout:
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "runtime_error",
            "feedback": "The C++ code raised a runtime error." + (f" Details: {stderr.splitlines()[-1][:220]}" if stderr else ""),
        }

    if "/" not in stdout:
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "runtime_error",
            "feedback": "The C++ evaluator could not read the test results.",
        }

    passed_text, total_text = stdout.split("/", 1)
    try:
        passed_tests = int(passed_text.strip())
        total_tests = int(total_text.strip())
    except ValueError:
        return {
            "passed_tests": 0,
            "total_tests": len(question.hidden_tests),
            "score": 0,
            "verdict": "runtime_error",
            "feedback": "The C++ evaluator received an invalid score payload.",
        }

    score = round((passed_tests / max(total_tests, 1)) * 100)
    if passed_tests == total_tests:
        verdict = "accepted"
        feedback = "Strong solve. All hidden tests passed in C++."
    elif passed_tests > 0:
        verdict = "partial"
        feedback = f"{passed_tests} of {total_tests} hidden tests passed. Review edge cases and return values."
    else:
        verdict = "failed"
        feedback = "No hidden tests passed yet. Recheck the C++ logic against the examples."
    return {
        "passed_tests": passed_tests,
        "total_tests": total_tests,
        "score": score,
        "verdict": verdict,
        "feedback": feedback,
    }


def evaluate_coding_submission(question: CodingQuestion, code: str, language: CodingLanguage) -> dict[str, object]:
    if language == "python":
        return evaluate_python_submission(question, code)
    if language == "cpp":
        return evaluate_cpp_submission(question, code)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported coding language.")


def resume_completion(student_id: int) -> int:
    resume = student_resumes.get(student_id)
    if resume is None:
        return 0
    values = resume.model_dump(exclude={"student_id", "updated_at"}).values()
    filled = sum(1 for value in values if str(value).strip())
    return round((filled / 12) * 100)


def resume_text(resume: StudentResume) -> str:
    return "\n".join(
        [
            resume.name,
            resume.role,
            resume.summary,
            resume.skills,
            resume.education,
            resume.projects,
            resume.experience,
            resume.achievements,
            resume.certifications,
        ]
    )


def keyword_candidates(job: Job) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z+#.]{2,}", f"{job.title} {job.description} {job.eligibility}")
    noisy = {"with", "and", "the", "for", "you", "will", "role", "build", "create", "students", "comfortable"}
    keywords = [item for item in job.skills + words if item.lower() not in noisy]
    normalized: list[str] = []
    for keyword in keywords:
        clean = keyword.strip()
        if clean and clean.lower() not in [item.lower() for item in normalized]:
            normalized.append(clean)
    return normalized[:18]


def deterministic_resume_check(job: Job, resume: StudentResume) -> ResumeCheckResult:
    text = resume_text(resume).lower()
    keywords = keyword_candidates(job)
    matched = [keyword for keyword in keywords if keyword.lower() in text]
    missing = [keyword for keyword in keywords if keyword.lower() not in text][:8]
    section_score = 0
    section_score += 15 if resume.email and resume.phone else 5
    section_score += 15 if resume.summary else 0
    section_score += 15 if resume.projects else 0
    section_score += 10 if resume.skills else 0
    keyword_score = round((len(matched) / max(len(keywords), 1)) * 45)
    score = min(100, section_score + keyword_score)
    weak_sections = []
    if missing:
        weak_sections.append("skills")
    if not resume.projects or any(keyword.lower() not in resume.projects.lower() for keyword in missing[:3]):
        weak_sections.append("projects")
    if job.title.split()[0].lower() not in resume.summary.lower():
        weak_sections.append("summary")
    suggestions = [
        f"Add {', '.join(missing[:4])} to skills or project bullets." if missing else "Keyword match looks strong.",
        "Add one measurable project result for this role.",
        f"Tailor the summary toward {job.title}.",
    ]
    patch = {
        "skills": ", ".join([item for item in [resume.skills, ", ".join(missing[:4])] if item]).strip(", "),
        "summary": (
            resume.summary
            if job.title.split()[0].lower() in resume.summary.lower()
            else f"{resume.summary} Interested in {job.title} roles with practical project experience."
        ).strip(),
        "projects": (
            resume.projects
            + (f"\nRole Match - Added {', '.join(missing[:3])} alignment for {job.title} responsibilities." if missing else "")
        ).strip(),
    }
    return ResumeCheckResult(
        score=score,
        verdict="Ready to apply" if score >= 75 else "Improve before applying",
        can_apply=score >= 75,
        matched_keywords=matched[:10],
        missing_keywords=missing,
        weak_sections=weak_sections[:4],
        suggestions=suggestions,
        suggested_resume_patch=patch,
    )


def extract_response_text(payload: dict[str, object]) -> str:
    if isinstance(payload.get("output_text"), str):
        return str(payload["output_text"])
    output = payload.get("output")
    if not isinstance(output, list):
        return ""
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                chunks.append(content["text"])
    return "\n".join(chunks)


def ai_resume_check(job: Job, resume: StudentResume) -> ResumeCheckResult:
    fallback = deterministic_resume_check(job, resume)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return fallback
    prompt = {
        "job": job.model_dump(mode="json"),
        "resume": resume.model_dump(mode="json"),
        "required_output": {
            "score": "integer 0-100",
            "verdict": "short string",
            "can_apply": "boolean, true when score >= 75",
            "matched_keywords": "array of strings",
            "missing_keywords": "array of strings",
            "weak_sections": "array using summary, skills, projects, experience, education",
            "suggestions": "array of specific student-friendly suggestions",
            "suggested_resume_patch": "object with optional summary, skills, projects, experience strings",
        },
    }
    body = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        "instructions": (
            "You are an ATS resume coach for fresher placement applications. "
            "Compare the resume against the job. Return only valid JSON with the exact required keys. "
            "Do not invent fake companies, degrees, or experience; only improve wording around supplied facts."
        ),
        "input": json.dumps(prompt),
    }
    try:
        req = request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=20) as response:
            response_payload = json.loads(response.read().decode("utf-8"))
        text = extract_response_text(response_payload).strip()
        parsed = json.loads(text)
        return ResumeCheckResult(**parsed)
    except (URLError, TimeoutError, json.JSONDecodeError, ValueError, KeyError):
        return fallback


def application_summary(application: JobApplication) -> dict[str, object]:
    job = find_job(application.job_id)
    return {
        "id": application.id,
        "job_id": job.id,
        "job_title": job.title,
        "company": job.company,
        "location": job.location,
        "status": application.status,
        "admin_note": application.admin_note,
        "ats_score": application.ats_score,
        "matched_keywords": application.matched_keywords,
        "missing_keywords": application.missing_keywords,
        "ai_suggestions": application.ai_suggestions,
        "applied_with_ai_fix": application.applied_with_ai_fix,
        "applied_at": application.applied_at,
        "updated_at": application.updated_at,
    }


def admin_application_detail(application: JobApplication) -> dict[str, object]:
    student = next(item for item in students if item.id == application.student_id)
    attempts = [attempt for attempt in mock_attempts if attempt.student_id == student.id]
    latest_attempt = max(attempts, key=lambda item: item.created_at) if attempts else None
    coding_history = [
        attempt
        for attempt in coding_attempts
        if attempt.student_id == student.id and attempt.status == "submitted"
    ]
    latest_coding = max(coding_history, key=lambda item: item.submitted_at or item.started_at) if coding_history else None
    return {
        "application_id": application.id,
        "status": application.status,
        "admin_note": application.admin_note,
        "ats_score": application.ats_score,
        "matched_keywords": application.matched_keywords,
        "missing_keywords": application.missing_keywords,
        "ai_suggestions": application.ai_suggestions,
        "applied_with_ai_fix": application.applied_with_ai_fix,
        "applied_at": application.applied_at,
        "updated_at": application.updated_at,
        "student": public_student(student),
        "resume_completion": resume_completion(student.id),
        "latest_mock_score": latest_attempt.score if latest_attempt else None,
        "latest_coding_score": latest_coding.total_score if latest_coding else None,
    }


def require_admin(authorization: str | None) -> None:
    if authorization != f"Bearer {ADMIN_TOKEN}":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin login is required.",
        )


def require_student(authorization: str | None) -> Student:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student login is required.",
        )
    token = authorization.removeprefix("Bearer ").strip()
    student_id = student_tokens.get(token)
    student = next((item for item in students if item.id == student_id), None)
    if student is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Student login is required.",
        )
    return student


def optional_student(authorization: str | None) -> Student | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.removeprefix("Bearer ").strip()
    student_id = student_tokens.get(token)
    return next((item for item in students if item.id == student_id), None)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/portal")
def get_portal() -> dict[str, object]:
    return {
        "club_name": "Programming Pathshala Club",
        "tagline": "Learn by building, sharing, and shipping real code.",
        "tracks": [
            {
                "title": "Python Foundations",
                "level": "Beginner",
                "duration": "4 weeks",
                "description": "Write clean Python, solve problems, and build command-line mini projects.",
            },
            {
                "title": "Web Dev Sprint",
                "level": "Intermediate",
                "duration": "6 weeks",
                "description": "Create responsive apps with Next.js, APIs, auth basics, and deployment habits.",
            },
            {
                "title": "DSA Practice Lab",
                "level": "All levels",
                "duration": "Ongoing",
                "description": "Practice patterns, discuss approaches, and prepare for coding interviews together.",
            },
        ],
        "events": ["Saturday code jam", "Peer review circle", "Project demo night"],
    }


@app.post("/api/admin/login")
def admin_login(payload: AdminLogin) -> dict[str, str]:
    if payload.email == ADMIN_EMAIL and payload.password == ADMIN_PASSWORD:
        return {"token": ADMIN_TOKEN, "email": ADMIN_EMAIL}
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid admin credentials.",
    )


@app.post("/api/admin/uploads")
async def upload_admin_asset(
    file: UploadFile = File(...),
    entity_type: str = Form(default="asset"),
    authorization: str | None = Header(default=None),
) -> dict[str, str]:
    require_admin(authorization)
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Upload a PDF, DOC, DOCX, PNG, JPG, JPEG, or WEBP file.",
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file is empty.")
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File must be 8 MB or smaller.")

    safe_entity = re.sub(r"[^a-z0-9-]+", "-", entity_type.lower()).strip("-") or "asset"
    stored_name = f"{safe_entity}-{uuid4().hex}{suffix}"
    stored_path = UPLOADS_DIR / stored_name
    stored_path.write_bytes(content)

    original_name = Path(file.filename or stored_name).name
    return {
        "filename": original_name,
        "url": f"/uploads/{stored_name}",
    }


@app.post("/api/students/register")
def student_register(payload: StudentRegister) -> dict[str, object]:
    if find_student_by_email(payload.email):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email is already registered.")
    if len(payload.password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password must be at least 6 characters.")
    student = Student(
        id=max((item.id for item in students), default=0) + 1,
        name=payload.name,
        email=payload.email,
        password_hash=hash_password(payload.password),
        phone=payload.phone,
        college=payload.college,
        course=payload.course,
        graduation_year=payload.graduation_year,
        skills=payload.skills,
        created_at=datetime.now(),
    )
    students.append(student)
    student_resumes[student.id] = StudentResume(
        student_id=student.id,
        name=student.name,
        email=student.email,
        phone=student.phone,
        skills=", ".join(student.skills),
        updated_at=datetime.now(),
    )
    token = f"student-{uuid4()}"
    student_tokens[token] = student.id
    return {"token": token, "student": public_student(student)}


@app.post("/api/students/login")
def student_login(payload: StudentLogin) -> dict[str, object]:
    student = find_student_by_email(payload.email)
    if student is None or student.password_hash != hash_password(payload.password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid student credentials.")
    token = f"student-{uuid4()}"
    student_tokens[token] = student.id
    return {"token": token, "student": public_student(student)}


@app.get("/api/students/me")
def student_me(authorization: str | None = Header(default=None)) -> StudentPublic:
    return public_student(require_student(authorization))


@app.get("/api/students/dashboard")
def student_dashboard(authorization: str | None = Header(default=None)) -> dict[str, object]:
    student = require_student(authorization)
    applications = [application for application in job_applications if application.student_id == student.id]
    latest_attempt = next(
        (
            attempt
            for attempt in sorted(mock_attempts, key=lambda item: item.created_at, reverse=True)
            if attempt.student_id == student.id
        ),
        None,
    )
    coding_history = [
        attempt
        for attempt in sorted(
            coding_attempts,
            key=lambda item: item.submitted_at or item.started_at,
            reverse=True,
        )
        if attempt.student_id == student.id and attempt.status == "submitted"
    ]
    latest_coding = coding_history[0] if coding_history else None
    return {
        "student": public_student(student),
        "resume_completion": resume_completion(student.id),
        "applied_jobs": len(applications),
        "latest_mock_score": latest_attempt.score if latest_attempt else None,
        "latest_coding_score": latest_coding.total_score if latest_coding else None,
        "applications": [application_summary(application) for application in applications],
        "mock_attempts": [attempt for attempt in mock_attempts if attempt.student_id == student.id],
        "coding_attempts": [coding_attempt_summary(attempt) for attempt in coding_history[:6]],
    }


@app.get("/api/students/resume")
def get_student_resume(authorization: str | None = Header(default=None)) -> StudentResume:
    student = require_student(authorization)
    return student_resumes.setdefault(
        student.id,
        StudentResume(
            student_id=student.id,
            name=student.name,
            email=student.email,
            phone=student.phone,
            skills=", ".join(student.skills),
            updated_at=datetime.now(),
        ),
    )


@app.put("/api/students/resume")
def save_student_resume(payload: StudentResume, authorization: str | None = Header(default=None)) -> StudentResume:
    student = require_student(authorization)
    resume = payload.model_copy(update={"student_id": student.id, "updated_at": datetime.now()})
    student_resumes[student.id] = resume
    return resume


@app.post("/api/students/resume/apply-ai-patch")
def apply_resume_patch(payload: ResumePatchRequest, authorization: str | None = Header(default=None)) -> StudentResume:
    student = require_student(authorization)
    resume = student_resumes.setdefault(
        student.id,
        StudentResume(student_id=student.id, name=student.name, email=student.email, phone=student.phone),
    )
    allowed_fields = {
        "role",
        "summary",
        "skills",
        "projects",
        "experience",
        "achievements",
        "certifications",
    }
    updates = {key: value for key, value in payload.patch.items() if key in allowed_fields and isinstance(value, str)}
    updated = resume.model_copy(update={**updates, "updated_at": datetime.now()})
    student_resumes[student.id] = updated
    return updated


@app.get("/api/jobs")
def list_jobs() -> list[Job]:
    return sorted(jobs, key=lambda job: job.last_date)


@app.post("/api/jobs/{job_id}/ai-resume-check")
def check_resume_for_job(job_id: int, authorization: str | None = Header(default=None)) -> ResumeCheckResult:
    student = require_student(authorization)
    job = find_job(job_id)
    resume = student_resumes.get(student.id)
    if resume is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Create a resume before applying.")
    return ai_resume_check(job, resume)


@app.post("/api/jobs/{job_id}/apply", status_code=status.HTTP_201_CREATED)
def apply_to_job(
    job_id: int,
    payload: JobApplyRequest | None = None,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    student = require_student(authorization)
    find_job(job_id)
    payload = payload or JobApplyRequest()
    existing = next(
        (
            application
            for application in job_applications
            if application.job_id == job_id and application.student_id == student.id
        ),
        None,
    )
    if existing:
        updated_existing = existing.model_copy(
            update={
                "ats_score": payload.ats_score if payload.ats_score is not None else existing.ats_score,
                "matched_keywords": payload.matched_keywords or existing.matched_keywords,
                "missing_keywords": payload.missing_keywords or existing.missing_keywords,
                "ai_suggestions": payload.ai_suggestions or existing.ai_suggestions,
                "applied_with_ai_fix": payload.applied_with_ai_fix or existing.applied_with_ai_fix,
                "updated_at": datetime.now(),
            }
        )
        job_applications[job_applications.index(existing)] = updated_existing
        return application_summary(updated_existing)
    application = JobApplication(
        id=max((item.id for item in job_applications), default=0) + 1,
        student_id=student.id,
        job_id=job_id,
        status="applied",
        ats_score=payload.ats_score,
        matched_keywords=payload.matched_keywords,
        missing_keywords=payload.missing_keywords,
        ai_suggestions=payload.ai_suggestions,
        applied_with_ai_fix=payload.applied_with_ai_fix,
        applied_at=datetime.now(),
        updated_at=datetime.now(),
    )
    job_applications.append(application)
    return application_summary(application)


@app.get("/api/students/applications")
def student_applications(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    student = require_student(authorization)
    return [
        application_summary(application)
        for application in job_applications
        if application.student_id == student.id
    ]


@app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
def create_job(payload: JobBase, authorization: str | None = Header(default=None)) -> Job:
    require_admin(authorization)
    job = Job(id=(max((item.id for item in jobs), default=0) + 1), **payload.model_dump())
    jobs.append(job)
    return job


@app.patch("/api/jobs/{job_id}")
def update_job(job_id: int, payload: JobBase, authorization: str | None = Header(default=None)) -> Job:
    require_admin(authorization)
    for index, job in enumerate(jobs):
        if job.id == job_id:
            updated = Job(id=job.id, **payload.model_dump())
            jobs[index] = updated
            return updated
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")


@app.delete("/api/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, authorization: str | None = Header(default=None)) -> None:
    require_admin(authorization)
    for index, job in enumerate(jobs):
        if job.id == job_id:
            jobs.pop(index)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")


@app.get("/api/admin/dashboard")
def admin_dashboard(authorization: str | None = Header(default=None)) -> dict[str, object]:
    require_admin(authorization)
    submitted_coding_attempts = [attempt for attempt in coding_attempts if attempt.status == "submitted"]
    return {
        "total_students": len(students),
        "total_jobs": len(jobs),
        "total_applications": len(job_applications),
        "total_events": len(events),
        "total_coding_attempts": len(submitted_coding_attempts),
        "average_mock_score": round(sum(attempt.score for attempt in mock_attempts) / len(mock_attempts), 1)
        if mock_attempts
        else None,
        "average_coding_score": round(
            sum(attempt.total_score for attempt in submitted_coding_attempts) / len(submitted_coding_attempts),
            1,
        )
        if submitted_coding_attempts
        else None,
    }


@app.get("/api/admin/students")
def admin_students(authorization: str | None = Header(default=None)) -> list[StudentPublic]:
    require_admin(authorization)
    return [public_student(student) for student in students]


@app.get("/api/admin/students/{student_id}")
def admin_student_detail(student_id: int, authorization: str | None = Header(default=None)) -> dict[str, object]:
    require_admin(authorization)
    student = next((item for item in students if item.id == student_id), None)
    if student is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found.")
    return {
        "student": public_student(student),
        "resume": student_resumes.get(student.id),
        "resume_completion": resume_completion(student.id),
        "applications": [
            application_summary(application)
            for application in job_applications
            if application.student_id == student.id
        ],
        "mock_attempts": [attempt for attempt in mock_attempts if attempt.student_id == student.id],
        "coding_attempts": [
            coding_attempt_summary(attempt)
            for attempt in coding_attempts
            if attempt.student_id == student.id
        ],
    }


@app.get("/api/admin/jobs")
def admin_jobs(authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    require_admin(authorization)
    result = []
    for job in jobs:
        related = [application for application in job_applications if application.job_id == job.id]
        status_counts = {
            key: sum(1 for application in related if application.status == key)
            for key in [
                "applied",
                "under_review",
                "shortlisted",
                "interview_scheduled",
                "selected",
                "rejected",
            ]
        }
        result.append(
            {
                **job.model_dump(),
                "total_applicants": len(related),
                "status_counts": status_counts,
            }
        )
    return result


@app.get("/api/admin/events")
def admin_events(authorization: str | None = Header(default=None)) -> list[Event]:
    require_admin(authorization)
    return sorted(events, key=lambda event: (event.event_date, event.event_time))


@app.get("/api/admin/jobs/{job_id}/applications")
def admin_job_applications(job_id: int, authorization: str | None = Header(default=None)) -> list[dict[str, object]]:
    require_admin(authorization)
    find_job(job_id)
    return [
        admin_application_detail(application)
        for application in job_applications
        if application.job_id == job_id
    ]


@app.get("/api/admin/jobs/{job_id}/applicants-export")
def export_job_applicants(job_id: int, authorization: str | None = Header(default=None)) -> Response:
    require_admin(authorization)
    job = find_job(job_id)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Application ID",
            "Status",
            "ATS Score",
            "Applied With AI Fix",
            "Matched Keywords",
            "Missing Keywords",
            "AI Suggestions",
            "Admin Note",
            "Applied At",
            "Student Name",
            "Email",
            "Phone",
            "College",
            "Course",
            "Graduation Year",
            "Student Skills",
            "Resume Completion",
            "Resume Role",
            "Resume Summary",
            "Resume Skills",
            "Education",
            "Projects",
            "Experience",
            "Achievements",
            "Certifications",
            "Links",
            "Latest Mock Score",
            "Job Title",
            "Company",
            "Location",
        ]
    )
    for application in [item for item in job_applications if item.job_id == job_id]:
        student = next(item for item in students if item.id == application.student_id)
        resume = student_resumes.get(student.id, StudentResume(student_id=student.id))
        attempts = [attempt for attempt in mock_attempts if attempt.student_id == student.id]
        latest_attempt = max(attempts, key=lambda item: item.created_at) if attempts else None
        writer.writerow(
            [
                application.id,
                application.status,
                application.ats_score or "",
                "Yes" if application.applied_with_ai_fix else "No",
                ", ".join(application.matched_keywords),
                ", ".join(application.missing_keywords),
                " | ".join(application.ai_suggestions),
                application.admin_note,
                application.applied_at.isoformat(),
                student.name,
                student.email,
                student.phone,
                student.college,
                student.course,
                student.graduation_year,
                ", ".join(student.skills),
                resume_completion(student.id),
                resume.role,
                resume.summary,
                resume.skills,
                resume.education,
                resume.projects,
                resume.experience,
                resume.achievements,
                resume.certifications,
                resume.links,
                latest_attempt.score if latest_attempt else "",
                job.title,
                job.company,
                job.location,
            ]
        )
    filename = re.sub(r"[^A-Za-z0-9-]+", "-", f"{job.company}-{job.title}-applicants").strip("-")
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}.csv"'},
    )


@app.patch("/api/admin/applications/{application_id}")
def update_application(
    application_id: int,
    payload: ApplicationUpdate,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    require_admin(authorization)
    application = next((item for item in job_applications if item.id == application_id), None)
    if application is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Application not found.")
    updated = application.model_copy(
        update={
            "status": payload.status,
            "admin_note": payload.admin_note,
            "updated_at": datetime.now(),
        }
    )
    index = job_applications.index(application)
    job_applications[index] = updated
    return admin_application_detail(updated)


@app.get("/api/events")
def list_events() -> list[Event]:
    return sorted(events, key=lambda event: (event.event_date, event.event_time))


@app.post("/api/events", status_code=status.HTTP_201_CREATED)
def create_event(payload: EventBase, authorization: str | None = Header(default=None)) -> Event:
    require_admin(authorization)
    event = Event(id=(max((item.id for item in events), default=0) + 1), **payload.model_dump())
    events.append(event)
    return event


@app.patch("/api/events/{event_id}")
def update_event(event_id: int, payload: EventBase, authorization: str | None = Header(default=None)) -> Event:
    require_admin(authorization)
    for index, event in enumerate(events):
        if event.id == event_id:
            updated = Event(id=event.id, **payload.model_dump())
            events[index] = updated
            return updated
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")


@app.delete("/api/events/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(event_id: int, authorization: str | None = Header(default=None)) -> None:
    require_admin(authorization)
    for index, event in enumerate(events):
        if event.id == event_id:
            events.pop(index)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found.")


@app.post("/api/coding-assessments/{assessment_id}/start")
def start_coding_assessment(
    assessment_id: int,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    student = require_student(authorization)
    assessment = find_coding_assessment(assessment_id)
    existing = next(
        (
            attempt
            for attempt in sorted(coding_attempts, key=lambda item: item.started_at, reverse=True)
            if attempt.student_id == student.id
            and attempt.assessment_id == assessment.id
            and attempt.status == "in_progress"
        ),
        None,
    )
    if existing:
        return coding_attempt_payload(existing)

    question_count = min(assessment.question_count, len(assessment.question_pool_ids))
    if question_count == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This assessment has no questions yet.")

    selected_question_ids = random.sample(assessment.question_pool_ids, question_count)
    attempt = CodingAttempt(
        id=max((item.id for item in coding_attempts), default=0) + 1,
        student_id=student.id,
        assessment_id=assessment.id,
        selected_question_ids=selected_question_ids,
        question_results=[
            CodingAttemptQuestionResult(question_id=question_id)
            for question_id in selected_question_ids
        ],
        started_at=datetime.now(),
    )
    coding_attempts.append(attempt)
    return coding_attempt_payload(attempt)


@app.get("/api/coding-attempts/{attempt_id}")
def get_coding_attempt(attempt_id: int, authorization: str | None = Header(default=None)) -> dict[str, object]:
    student = require_student(authorization)
    attempt = next((item for item in coding_attempts if item.id == attempt_id), None)
    if attempt is None or attempt.student_id != student.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding attempt not found.")
    return coding_attempt_payload(attempt)


@app.post("/api/coding-attempts/{attempt_id}/questions/{question_id}/submit")
def submit_coding_question(
    attempt_id: int,
    question_id: int,
    payload: CodingSubmissionRequest,
    authorization: str | None = Header(default=None),
) -> dict[str, object]:
    student = require_student(authorization)
    attempt = next((item for item in coding_attempts if item.id == attempt_id), None)
    if attempt is None or attempt.student_id != student.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding attempt not found.")
    if attempt.status == "submitted":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This assessment is already finished.")
    if question_id not in attempt.selected_question_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Question is not part of this attempt.")

    question = find_coding_question(question_id)
    if payload.language not in question.languages:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This language is not enabled for the selected question.")
    evaluation = evaluate_coding_submission(question, payload.code, payload.language)
    current_result = coding_attempt_result(attempt, question_id)
    updated_result = current_result.model_copy(
        update={
            "language": payload.language,
            "code": payload.code,
            "passed_tests": evaluation["passed_tests"],
            "total_tests": evaluation["total_tests"],
            "score": evaluation["score"],
            "verdict": evaluation["verdict"],
            "feedback": evaluation["feedback"],
            "last_submitted_at": datetime.now(),
        }
    )
    updated_attempt = attempt.model_copy(
        update={
            "question_results": [
                updated_result if result.question_id == question_id else result
                for result in attempt.question_results
            ]
        }
    )
    updated_attempt = recalculate_coding_attempt(updated_attempt)
    coding_attempts[coding_attempts.index(attempt)] = updated_attempt
    return coding_attempt_payload(updated_attempt)


@app.post("/api/coding-attempts/{attempt_id}/finish")
def finish_coding_attempt(attempt_id: int, authorization: str | None = Header(default=None)) -> dict[str, object]:
    student = require_student(authorization)
    attempt = next((item for item in coding_attempts if item.id == attempt_id), None)
    if attempt is None or attempt.student_id != student.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Coding attempt not found.")
    if attempt.status == "submitted":
        return coding_attempt_payload(attempt)

    updated_attempt = recalculate_coding_attempt(
        attempt.model_copy(
            update={
                "status": "submitted",
                "submitted_at": datetime.now(),
            }
        )
    )
    coding_attempts[coding_attempts.index(attempt)] = updated_attempt
    return coding_attempt_payload(updated_attempt)


@app.post("/api/mock-interview/questions")
def generate_mock_questions(payload: InterviewRequest) -> dict[str, object]:
    skills = [skill.strip() for skill in payload.skills if skill.strip()]
    if not skills:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one skill.")

    questions = [
        f"For a {payload.role} role, explain one project where you used {skills[0]} and what tradeoff you made.",
        f"What is a common mistake beginners make with {skills[min(1, len(skills) - 1)]}, and how would you avoid it?",
        "Tell me about a time you debugged something difficult. What did you try first?",
    ]
    if payload.round_type in {"technical", "mixed"}:
        questions.append(f"Design a small feature using {', '.join(skills[:3])}. How would you split the work?")
    if payload.round_type in {"hr", "mixed"}:
        questions.append("Why should a team trust you with a deadline-sensitive task?")

    return {"role": payload.role, "round_type": payload.round_type, "questions": questions}


def interview_skills(payload: InterviewRequest) -> list[str]:
    return [skill.strip() for skill in payload.skills if skill.strip()]


def call_ollama(prompt: str) -> str | None:
    endpoint = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
    model = os.getenv("OLLAMA_MODEL", "llama3.1")
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.55, "num_predict": 260},
        }
    ).encode("utf-8")
    try:
        api_request = request.Request(
            endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(api_request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception:
        return None
    answer = str(data.get("response", "")).strip()
    return answer or None


def fallback_interview_question(role: str, round_type: str, skills: list[str], turn: int, difficulty: str = "intermediate") -> str:
    primary = skills[(turn - 1) % len(skills)]
    if difficulty == "beginner":
        depth = "explain it simply, including what you personally did"
    elif difficulty == "advanced":
        depth = "go deep on architecture, tradeoffs, failure cases, and measurable impact"
    else:
        depth = "cover the project, your decision, and the result"
    questions = [
        f"Walk me through one real project where you used {primary}. Please {depth}.",
        f"I am going to push deeper on {primary}. What was the hardest technical decision you made and why?",
        f"Imagine this project breaks in production. How would you debug it step by step?",
        f"For a {role} role, how would you explain your impact to a non-technical manager?",
        "Tell me about one weakness in your current preparation and what you are doing to improve it.",
    ]
    if round_type == "hr":
        questions = [
            "Tell me about yourself like this is the first two minutes of a real interview.",
            "Describe a time you handled pressure or a deadline. What did you do first?",
            f"Why are you interested in a {role} role, and what makes you ready for it?",
            "Tell me about a disagreement in a team. How did you handle it?",
            "What should I remember about you after this interview?",
        ]
    return questions[min(turn - 1, len(questions) - 1)]


def generate_interview_question(session: dict[str, object], turn: int, last_answer: str = "") -> tuple[str, str]:
    role = str(session["role"])
    round_type = str(session["round_type"])
    difficulty = str(session.get("difficulty", "intermediate"))
    skills = session["skills"]
    transcript = session["transcript"]
    skills_text = ", ".join(skills) if isinstance(skills, list) else str(skills)
    transcript_text = "\n".join(
        f"{item['speaker']}: {item['text']}" for item in transcript[-8:]
    ) if isinstance(transcript, list) else ""
    prompt = (
        "You are a calm but realistic human interviewer. Ask exactly one concise interview question. "
        "Do not add explanation, scoring, markdown, or multiple questions.\n"
        f"Role: {role}\nRound: {round_type}\nSkills: {skills_text}\nTurn: {turn}/5\n"
        f"Difficulty: {difficulty}\n"
        f"Latest candidate answer: {last_answer or 'No answer yet'}\n"
        f"Recent transcript:\n{transcript_text}\n"
        "Ask a natural follow-up if the answer needs depth; otherwise move to the next useful question."
    )
    question = call_ollama(prompt)
    if question:
        return question, "ollama"
    skills_list = skills if isinstance(skills, list) else [str(skills)]
    return fallback_interview_question(role, round_type, skills_list, turn, difficulty), "fallback"


def fallback_interview_feedback(session: dict[str, object]) -> dict[str, object]:
    skills = session["skills"] if isinstance(session["skills"], list) else []
    answers = session["answers"] if isinstance(session["answers"], list) else []
    combined = " ".join(str(answer) for answer in answers)
    word_count = len(combined.split())
    matched_skills = [skill for skill in skills if str(skill).lower() in combined.lower()]
    score = min(10, max(4, word_count // 35 + len(matched_skills) + 3))
    suggestions = [
        "Answer with a sharper opening line before giving background.",
        "Add one measurable result, scale, or business impact from your project.",
        "Use the STAR structure when the question is behavioral: situation, task, action, result.",
    ]
    if len(matched_skills) < min(2, len(skills)):
        suggestions.insert(0, "Connect your answer to the required skills more directly.")
    return {
        "score": score,
        "strength": "You stayed relevant and gave the interviewer enough material to continue."
        if word_count > 80
        else "You have the base of the answer, but it needs more specific evidence.",
        "suggestions": suggestions[:4],
        "sample_answer": (
            "A stronger answer would name the project, state your exact responsibility, explain the hard "
            "decision, and close with the result or what changed because of your work."
        ),
    }


def fallback_answer_coaching(question: str, answer: str, skills: list[str], role: str) -> dict[str, object]:
    words = answer.split()
    matched_skills = [skill for skill in skills if skill.lower() in answer.lower()]
    needs_metric = not re.search(r"\b\d+[%x]?\b|\busers?\b|\bseconds?\b|\bminutes?\b|\breduced\b|\bimproved\b", answer.lower())
    needs_structure = len(words) < 45
    suggestions = []
    if needs_structure:
        suggestions.append("Give more context: project, responsibility, challenge, action, and result.")
    if needs_metric:
        suggestions.append("Add one measurable result or concrete outcome.")
    if not matched_skills:
        suggestions.append("Mention the relevant skill directly and connect it to your work.")
    suggestions.append("End with what you learned or how you would improve it now.")
    return {
        "score": min(10, max(4, len(words) // 18 + len(matched_skills) + 4)),
        "what_worked": "You answered in the right direction and stayed connected to the question."
        if len(words) >= 25
        else "You started answering the question, but the interviewer needs more evidence.",
        "missing": suggestions[:3],
        "better_answer": (
            f"For this {role} answer, I would name the project first, explain the exact problem, "
            f"describe how I used {matched_skills[0] if matched_skills else skills[0]}, and close with the result."
        ),
    }


def generate_answer_coaching(question: str, answer: str, skills: list[str], role: str, difficulty: str = "intermediate") -> dict[str, object]:
    prompt = (
        "You are an interview coach. Give feedback for this one candidate answer. "
        "Return only valid JSON with keys: score as integer 1-10, what_worked as one sentence, "
        "missing as an array of 3 short answer-specific suggestions, better_answer as a compact improved answer.\n"
        f"Role: {role}\nDifficulty: {difficulty}\nSkills: {', '.join(skills)}\nQuestion: {question}\nCandidate answer: {answer}"
    )
    raw = call_ollama(prompt)
    if raw:
        try:
            match = re.search(r"\{[\s\S]*\}", raw)
            data = json.loads(match.group(0) if match else raw)
            missing = [str(item) for item in data.get("missing", []) if str(item).strip()]
            return {
                "score": min(10, max(1, int(data.get("score", 6)))),
                "what_worked": str(data.get("what_worked", "Your answer has a clear starting point.")),
                "missing": missing[:3],
                "better_answer": str(data.get("better_answer", "")),
            }
        except Exception:
            pass
    return fallback_answer_coaching(question, answer, skills, role)


def generate_interview_feedback(session: dict[str, object]) -> dict[str, object]:
    transcript = session["transcript"]
    transcript_text = "\n".join(
        f"{item['speaker']}: {item['text']}" for item in transcript
    ) if isinstance(transcript, list) else ""
    prompt = (
        "Review this mock interview transcript. Return only valid JSON with keys: "
        "score as an integer from 1 to 10, strength as one sentence, suggestions as an array of 4 short strings, "
        "sample_answer as one compact paragraph.\n"
        f"Role: {session['role']}\nRound: {session['round_type']}\nDifficulty: {session.get('difficulty', 'intermediate')}\nSkills: {', '.join(session['skills'])}\n"
        f"Transcript:\n{transcript_text}"
    )
    raw = call_ollama(prompt)
    if raw:
        try:
            match = re.search(r"\{[\s\S]*\}", raw)
            data = json.loads(match.group(0) if match else raw)
            return {
                "score": int(data.get("score", 6)),
                "strength": str(data.get("strength", "You gave usable answers with room to sharpen.")),
                "suggestions": [str(item) for item in data.get("suggestions", [])][:4],
                "sample_answer": str(data.get("sample_answer", "")),
            }
        except Exception:
            pass
    return fallback_interview_feedback(session)


@app.post("/api/mock-interview/start")
def start_live_mock_interview(payload: InterviewRequest) -> dict[str, object]:
    skills = interview_skills(payload)
    if not skills:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Add at least one skill.")
    session_id = f"interview-{uuid4()}"
    session: dict[str, object] = {
        "id": session_id,
        "role": payload.role,
        "round_type": payload.round_type,
        "difficulty": payload.difficulty,
        "skills": skills,
        "turn": 1,
        "transcript": [],
        "answers": [],
        "created_at": datetime.now(),
    }
    question, provider = generate_interview_question(session, 1)
    session["transcript"].append({"speaker": "Interviewer", "text": question})
    interview_sessions[session_id] = session
    return {
        "session_id": session_id,
        "question": question,
        "turn": 1,
        "max_turns": 5,
        "provider": provider,
        "message": "Local AI interviewer is live." if provider == "ollama" else "Fallback interviewer is live. Start Ollama for local AI depth.",
    }


@app.post("/api/mock-interview/respond")
def respond_live_mock_interview(payload: InterviewSessionReply) -> dict[str, object]:
    session = interview_sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found.")
    answer = payload.answer.strip()
    if not answer:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Speak or write an answer first.")
    session["answers"].append(answer)
    session["transcript"].append({"speaker": "Candidate", "text": answer})
    current_turn = int(session["turn"])
    questions = [
        item["text"]
        for item in session["transcript"]
        if isinstance(item, dict) and item.get("speaker") == "Interviewer"
    ]
    current_question = str(questions[-1]) if questions else ""
    skills = [str(skill) for skill in session["skills"]] if isinstance(session["skills"], list) else []
    answer_coaching = generate_answer_coaching(current_question, answer, skills, str(session["role"]), str(session.get("difficulty", "intermediate")))
    if current_turn >= 5:
        return {
            "session_id": payload.session_id,
            "is_complete": True,
            "question": "",
            "turn": current_turn,
            "max_turns": 5,
            "answer_coaching": answer_coaching,
            "message": "Good. That completes this mock interview. End the session for your score.",
        }
    next_turn = current_turn + 1
    question, provider = generate_interview_question(session, next_turn, answer)
    session["turn"] = next_turn
    session["transcript"].append({"speaker": "Interviewer", "text": question})
    return {
        "session_id": payload.session_id,
        "is_complete": False,
        "question": question,
        "turn": next_turn,
        "max_turns": 5,
        "provider": provider,
        "answer_coaching": answer_coaching,
        "message": "Follow-up ready.",
    }


@app.post("/api/mock-interview/end")
def end_live_mock_interview(payload: InterviewSessionReply, authorization: str | None = Header(default=None)) -> dict[str, object]:
    session = interview_sessions.get(payload.session_id)
    if session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview session not found.")
    if payload.answer.strip():
        session["answers"].append(payload.answer.strip())
        session["transcript"].append({"speaker": "Candidate", "text": payload.answer.strip()})
    feedback = generate_interview_feedback(session)
    student = optional_student(authorization)
    if student is not None:
        questions = [
            item["text"]
            for item in session["transcript"]
            if isinstance(item, dict) and item.get("speaker") == "Interviewer"
        ]
        answers = session["answers"] if isinstance(session["answers"], list) else []
        mock_attempts.append(
            MockInterviewAttempt(
                id=max((attempt.id for attempt in mock_attempts), default=0) + 1,
                student_id=student.id,
                role=str(session["role"]),
                round_type=str(session["round_type"]),
                skills=[str(skill) for skill in session["skills"]],
                question="\n".join(str(question) for question in questions),
                answer="\n\n".join(str(answer) for answer in answers),
                score=int(feedback["score"]),
                strength=str(feedback["strength"]),
                suggestions=[str(item) for item in feedback["suggestions"]],
                sample_answer=str(feedback["sample_answer"]),
                created_at=datetime.now(),
            )
        )
    interview_sessions.pop(payload.session_id, None)
    return {
        **feedback,
        "saved": student is not None,
    }


@app.post("/api/mock-interview/feedback")
def review_interview_answer(payload: InterviewAnswer) -> dict[str, object]:
    word_count = len(payload.answer.split())
    mentioned_skills = [
        skill for skill in payload.skills if skill.lower() in payload.answer.lower()
    ]
    score = min(10, max(4, word_count // 8 + len(mentioned_skills)))
    suggestions = [
        "Start with a direct answer before adding context.",
        "Use one concrete project, metric, or result to make the answer stronger.",
        "Close with what you learned or how you would improve next time.",
    ]
    if not mentioned_skills:
        suggestions.insert(0, "Mention the relevant skill directly and connect it to your example.")

    return {
        "score": score,
        "strength": "Your answer has enough direction to build from." if word_count > 20 else "Good start, but it needs more detail.",
        "suggestions": suggestions[:3],
        "sample_answer": (
            "I would answer by naming the project, explaining the exact responsibility I owned, "
            "describing one challenge, and ending with the measurable result or lesson."
        ),
    }


@app.get("/api/classes")
def list_classes(class_date: date | None = None) -> list[ClassSchedule]:
    if class_date is None:
        return classes
    return [item for item in classes if item.class_date == class_date]
