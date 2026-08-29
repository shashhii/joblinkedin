#!/usr/bin/env python3
"""
ATS-Friendly Resume Generator for Shashikumar S
Self-contained — ALL resume data embedded, no external files needed.
Designed for Android Termux usage.

Usage:
  python3 resume.py                                  # Interactive prompt for job description
  python3 resume.py --job "JD text here"              # Tailored to job description
  python3 resume.py --job-file jd.txt                 # Tailored from file
  python3 resume.py --no-summary                      # Omit summary section
  python3 resume.py -o my_resume.pdf                  # Custom output path

Requirements: reportlab (pip install reportlab)
"""

import argparse
import re
import os
import sys
from collections import Counter

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import Color
    from reportlab.pdfgen import canvas
except ImportError:
    print("=" * 60)
    print("ERROR: reportlab is not installed!")
    print("=" * 60)
    print("Install it with one of these commands:")
    print("  pip install reportlab")
    print("  pip3 install reportlab")
    print("  pkg install python && pip install reportlab  (Termux)")
    print("")
    print("Or run install.sh for automatic setup.")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# EMBEDDED RESUME DATA (no external JSON needed)
# ══════════════════════════════════════════════════════════════════════════════

RESUME_DATA = {
    "personal": {
        "name": "SHASHIKUMAR S",
        "phone": "+91 95380 80482",
        "email": "admin@shashhii.online",
        "linkedin": "linkedin.com/in/shashhii",
        "github": "github.com/shashhii",
        "leetcode": "leetcode.com/u/shashi_0804",
        "website": "shashhii.online"
    },
    "summary": "",
    "education": [
        {
            "institution": "Maharaja Institute of Technology, Mysore",
            "degree": "Bachelor of Engineering in Computer Science & Engineering",
            "cgpa": "7.9 / 10",
            "start": "Dec 2022",
            "end": "May 2026"
        }
    ],
    "experience": [
        {
            "title": "App Development Intern",
            "company": "MindMatrixEd\u2014E-Learning Providers, Bengaluru, KA",
            "start": "Jan 2026",
            "end": "June 2026",
            "bullets": [
                {
                    "text": "Developing a production-grade Android application integrating Generative AI features to deliver personalized, industry-aligned learning experiences for engineering students.",
                    "keywords": ["Android", "Generative AI", "personalized"],
                    "bold_phrases": ["production-grade Android application", "Generative AI", "personalized", "learning experiences"]
                },
                {
                    "text": "Built a Live Currency Converter app supporting 188+ global currencies with real-time exchange-rate API integration, delivering sub-second refresh rates and packaged as a cross-platform Android APK.",
                    "keywords": ["Currency Converter", "API", "refresh rates", "Android APK"],
                    "bold_phrases": ["Live Currency Converter app", "188+ global currencies", "real-time exchange-rate API integration", "sub-second refresh rates", "Android APK"]
                },
                {
                    "text": "Leveraging AI-powered content generation to automate course recommendations, quiz creation, and adaptive learning paths, reducing manual content effort by an estimated 40%.",
                    "keywords": ["AI-powered", "automate", "content"],
                    "bold_phrases": ["AI-powered content generation", "automate course recommendations", "adaptive learning paths", "40%"]
                },
                {
                    "text": "Architecting modular, scalable app components using clean code principles, improving maintainability and enabling rapid feature iteration across the platform.",
                    "keywords": ["modular", "clean code", "maintainability"],
                    "bold_phrases": ["modular, scalable app components", "clean code principles", "maintainability", "rapid feature iteration"]
                },
                {
                    "text": "Collaborating with cross-functional teams to align app features with real-world industry curriculum requirements for 1,000+ engineering students.",
                    "keywords": ["collaborating", "curriculum", "students"],
                    "bold_phrases": ["cross-functional teams", "real-world industry curriculum requirements", "1,000+ engineering students"]
                }
            ]
        },
        {
            "title": "Web Development Intern",
            "company": "TechnoHacks Solutions Pvt. Ltd., Mysore, KA",
            "start": "Aug 2025",
            "end": "Oct 2025",
            "bullets": [
                {
                    "text": "Engineered responsive, production-ready web applications using HTML, CSS, JavaScript, and React.js, implementing responsive design and performance optimization techniques.",
                    "keywords": ["HTML", "CSS", "JavaScript", "React.js", "responsive"],
                    "bold_phrases": ["responsive, production-ready web applications", "HTML, CSS, JavaScript, and React.js", "performance optimization"]
                },
                {
                    "text": "Utilized Visual Studio Code, Git, and browser Developer Tools for end-to-end web development, including debugging, cross-browser testing, and integration of REST APIs.",
                    "keywords": ["VS Code", "Git", "Developer Tools", "REST APIs"],
                    "bold_phrases": ["Visual Studio Code, Git, and browser Developer Tools", "end-to-end web development", "REST APIs"]
                },
                {
                    "text": "Applied advanced JavaScript, React.js, and Node.js concepts to build modular application architecture, reusable components, and clean code, reducing development time by 30%.",
                    "keywords": ["JavaScript", "React.js", "Node.js", "modular", "clean code"],
                    "bold_phrases": ["advanced JavaScript, React.js, and Node.js concepts", "modular application architecture", "reusable components", "30%"]
                },
                {
                    "text": "Delivered 2 fully functional web applications within a 6-week internship cycle, meeting all project milestones on schedule while ensuring responsive performance, accessibility, and code quality.",
                    "keywords": ["applications", "internship", "milestones"],
                    "bold_phrases": ["2 fully functional web applications", "6-week internship cycle", "responsive performance, accessibility, and code quality"]
                }
            ]
        }
    ],
    "projects": [
        {
            "title": "Camouflaged Object Detection (COD)",
            "tech": "Python, SINet V2, PyTorch, TensorFlow, CUDA",
            "start": "Jul 2025",
            "end": "Aug 2025",
            "github": "github.com/shashhii/COD",
            "link": "cod-769q.onrender.com",
            "bullets": [
                {
                    "text": "Developed a deep learning model using SINet V2 to detect camouflaged objects in complex, low contrast backgrounds with high precision across 20,000+ training images from CAMO and COD10K datasets.",
                    "keywords": ["deep learning", "SINet V2", "camouflaged", "CAMO", "COD10K"],
                    "bold_phrases": ["deep learning model", "SINet V2", "camouflaged objects", "20,000+ training images", "CAMO and COD10K datasets"]
                },
                {
                    "text": "Trained for 100 epochs with CUDA acceleration, achieving significant improvements in detection speed and segmentation accuracy over baseline models.",
                    "keywords": ["epochs", "CUDA", "segmentation", "accuracy"],
                    "bold_phrases": ["100 epochs", "CUDA acceleration", "detection speed and segmentation accuracy"]
                },
                {
                    "text": "Built a complete computer vision pipeline covering preprocessing, augmentation, segmentation, and performance evaluation \u2014 generalizes to any image type beyond training distribution.",
                    "keywords": ["computer vision", "pipeline", "segmentation"],
                    "bold_phrases": ["computer vision pipeline", "preprocessing, augmentation, segmentation", "generalizes to any image type"]
                },
                {
                    "text": "Deployed a live web application enabling real-time inference, with applications in medical imaging, military surveillance, wildlife monitoring, and CCTV security.",
                    "keywords": ["web application", "inference", "surveillance"],
                    "bold_phrases": ["live web application", "real-time inference", "medical imaging, military surveillance, wildlife monitoring, and CCTV security"]
                }
            ]
        },
        {
            "title": "MERN Ecommerce App",
            "tech": "MongoDB, Express.js, React.js, Node.js, JWT",
            "start": "2024",
            "end": "",
            "github": "github.com/shashhii/MERN-Ecommerce-App",
            "link": "",
            "bullets": [
                {
                    "text": "Engineered a full-stack e-commerce platform with product listings, JWT-based secure authentication, shopping cart, checkout flow, and an admin dashboard for complete store management.",
                    "keywords": ["full-stack", "e-commerce", "JWT", "admin dashboard"],
                    "bold_phrases": ["full-stack e-commerce platform", "JWT-based secure authentication", "admin dashboard", "store management"]
                },
                {
                    "text": "Implemented RESTful APIs with Express.js and MongoDB, handling end-to-end data flow from product creation to order fulfillment with real-time inventory updates.",
                    "keywords": ["RESTful APIs", "Express.js", "MongoDB", "inventory"],
                    "bold_phrases": ["RESTful APIs", "Express.js and MongoDB", "end-to-end data flow", "real-time inventory updates"]
                },
                {
                    "text": "Built a responsive React.js frontend with dynamic state management, reducing page load time and delivering a seamless shopping experience across all devices.",
                    "keywords": ["React.js", "frontend", "state management", "devices"],
                    "bold_phrases": ["responsive React.js frontend", "dynamic state management", "seamless shopping experience"]
                },
                {
                    "text": "Designed role-based access control separating admin and user permissions, ensuring secure and scalable multi-user operations.",
                    "keywords": ["role-based", "permissions", "multi-user"],
                    "bold_phrases": ["role-based access control", "admin and user permissions", "secure and scalable multi-user operations"]
                }
            ]
        }
    ],
    "skills": {
        "Languages": ["Java", "Python", "C/C++", "Dart", "JavaScript", "SQL", "HTML/CSS", "Kotlin", "TypeScript"],
        "Frameworks": ["React.js", "Node.js", "Flutter", "Flask", "FastAPI", "Next.js", "Tailwind CSS", "Bootstrap"],
        "Dev Tools": ["Git", "Android Studio", "VS Code", "Docker", "Firebase", "AWS", "Google Cloud Platform", "Anaconda"],
        "Libraries": ["TensorFlow", "PyTorch", "OpenCV", "Pandas", "NumPy", "Matplotlib", "Scikit-learn"],
        "Databases": ["MySQL", "MongoDB", "PostgreSQL", "Firebase Firestore"]
    },
    "certifications": [
        {"name": "Oracle Cloud Infrastructure 2025 \u2013 Generative AI Professional", "issuer": "Oracle", "date": "Sep 2025", "url": "https://catalog-education.oracle.com/ords/certview/sharebadge?id=4DD471C9DC0D78C6E53008AE47AFDA6D27ECC744AA2E9BD37A78047DE0A175A9"},
        {"name": "Oracle Cloud Infrastructure 2025 \u2013 AI Foundations Associate", "issuer": "Oracle", "date": "Aug 2025", "url": "https://catalog-education.oracle.com/ords/certview/sharebadge?id=9E962504DCA532D4AC6FD7B09357C37AA224E384F7D1BF2B31F1D407D261A921"},
        {"name": "Microsoft Azure AI Fundamentals (AI-900)", "issuer": "Microsoft", "date": "Jul 2025", "url": "https://www.linkedin.com/learning/certificates/79046a3b5582410fb57af201cad22aebcbb19c302a0070c753b28983209120d0"},
        {"name": "Artificial Intelligence Fundamentals", "issuer": "IBM", "date": "Nov 2025", "url": "https://www.credly.com/badges/ec03a196-8838-4780-b8d9-698c9d6073dd"},
        {"name": "Docker Foundations Professional Certificate", "issuer": "Docker", "date": "Aug 2025", "url": "https://www.linkedin.com/learning/certificates/cbb69d8efae65822bab5a57b3eb3982d5cb1b1cb5fa783fc7dd78b03a4664a48"},
        {"name": "ChatGPT Prompt Engineering for Developers", "issuer": "DeepLearning.AI", "date": "", "url": "https://learn.deeplearning.ai/accomplishments/5ee60152-16a0-4cab-8ca2-d9270dfe951a?usp=sharing"},
        {"name": "GenAI Powered Data Analytics Job Simulation", "issuer": "TCS", "date": "Aug 2025", "url": "https://forage-uploads-prod.s3.amazonaws.com/completion-certificates/ifobHAoMjQs9s6bKS/gMTdCXwDdLYoXZ3wG_ifobHAoMjQs9s6bKS_ZmHvuDsYXRLCXonaF_1755531420422_completion_certificate.pdf"},
        {"name": "AWS \u2013 Introduction to Generative AI: Art of the Possible", "issuer": "Amazon Web Services", "date": "", "url": "https://www.linkedin.com/in/shashhii/details/certifications/"},
        {"name": "Software Engineer Certificate", "issuer": "HackerRank", "date": "ID: A38C53A2F519", "url": "https://www.hackerrank.com/certificates/a38c53a2f519"}
    ]
}


# ══════════════════════════════════════════════════════════════════════════════
# STYLING CONSTANTS (matching original PDF exactly)
# ══════════════════════════════════════════════════════════════════════════════

PAGE_WIDTH, PAGE_HEIGHT = A4  # 595 x 842 pts
MARGIN_LEFT = 45
MARGIN_RIGHT = 45
MARGIN_TOP = 40
MARGIN_BOTTOM = 40
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_LEFT - MARGIN_RIGHT

# Colors
COLOR_DARK   = Color(26/255,  26/255,  26/255)   # rgb(26,26,26)   — main text
COLOR_MEDIUM = Color(68/255,  68/255,  68/255)   # rgb(68,68,68)   — dates, secondary
COLOR_LIGHT  = Color(153/255, 153/255, 153/255)   # rgb(153,153,153) — separators
COLOR_LINK   = Color(0/255,   0/255,   238/255)   # rgb(0,0,238)    — links
COLOR_LINE   = Color(180/255, 180/255, 180/255)   # subtle section divider

# Font sizes
FONT_NAME_SIZE        = 24
FONT_CONTACT_SIZE     = 9.5
FONT_SECTION_SIZE     = 11
FONT_JOB_TITLE_SIZE   = 10.5
FONT_BODY_SIZE        = 10
FONT_SMALL_SIZE       = 9.5
FONT_TECH_SIZE        = 9.5

# Spacing
SECTION_SPACING  = 12
JOB_TITLE_SPACING = 4
COMPANY_SPACING  = 4
BULLET_SPACING   = 3
LINE_HEIGHT      = 14


# ══════════════════════════════════════════════════════════════════════════════
# KEYWORD EXTRACTION & SCORING
# ══════════════════════════════════════════════════════════════════════════════

STOP_WORDS = {
    'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
    'of', 'with', 'by', 'from', 'as', 'is', 'was', 'are', 'were', 'be',
    'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will',
    'would', 'could', 'should', 'may', 'might', 'shall', 'can', 'need',
    'dare', 'ought', 'used', 'this', 'that', 'these', 'those', 'i', 'me',
    'my', 'we', 'our', 'you', 'your', 'he', 'him', 'his', 'she', 'her',
    'it', 'its', 'they', 'them', 'their', 'what', 'which', 'who', 'whom',
    'where', 'when', 'why', 'how', 'all', 'each', 'every', 'both', 'few',
    'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only',
    'own', 'same', 'so', 'than', 'too', 'very', 'just', 'because', 'if',
    'then', 'else', 'about', 'up', 'out', 'off', 'over', 'under', 'again',
    'further', 'here', 'there', 'once', 'during', 'before', 'after',
    'above', 'below', 'between', 'through', 'into', 'also', 'well',
    'using', 'used', 'via', 'including', 'across', 'within', 'without',
    'while', 'etc', 'e.g', 'i.e', 'per', 'vs', 'etc.', 'ensuring',
    'ability', 'able', 'looking', 'seeking', 'experience', 'years',
    'must', 'required', 'preferred', 'including', 'knowledge',
    'understanding', 'familiar', 'strong', 'excellent', 'good',
    'new', 'work', 'role', 'position', 'team', 'job', 'company',
}

TECH_SYNONYMS = {
    'javascript': ['js', 'es6', 'es2015', 'ecmascript', 'vanilla js'],
    'react': ['reactjs', 'react.js'],
    'node': ['nodejs', 'node.js'],
    'python': ['py'],
    'java': ['jdk', 'jvm'],
    'machine learning': ['ml'],
    'deep learning': ['dl', 'neural network', 'neural networks'],
    'artificial intelligence': ['ai', 'machine learning', 'ml', 'deep learning', 'dl', 'natural language processing', 'nlp', 'computer vision', 'cv', 'neural network', 'neural networks', 'transformers', 'pytorch', 'tensorflow', 'keras', 'generative ai', 'sinet v2', 'res2net'],
    'computer vision': ['cv', 'image processing', 'object detection', 'segmentation'],
    'natural language processing': ['nlp', 'text summarization', 'transformers', 'hugging face'],
    'flutter': ['dart'],
    'rest api': ['restful', 'rest apis'],
    'sql': ['mysql', 'postgresql', 'rdbms'],
    'nosql': ['mongodb', 'firebase', 'dynamodb'],
    'docker': ['container', 'containers', 'kubernetes', 'k8s'],
    'aws': ['amazon web services', 'ec2', 's3', 'lambda'],
    'git': ['github', 'gitlab', 'bitbucket', 'version control'],
    'agile': ['scrum', 'sprint'],
    'support': ['helpdesk', 'service desk', 'troubleshooting', 'maintenance', 'customer service', 'it support', 'desktop support', 'ticketing', 'diagnose', 'resolve'],
    'security': ['authentication', 'passwords', 'user accounts', 'permissions', 'auth', 'access control', 'secure'],
    'database': ['sql server', 'postgresql', 'mysql', 'mongodb', 'database schema', 'queries', 'database design', 'sql'],
    'software': ['application', 'system', 'tool', 'platform', 'portal', 'dashboard', 'full-stack', 'full stack', 'backend', 'frontend', 'web app', 'developer', 'development'],
}


def extract_keywords(text):
    """Extract meaningful keywords from job description text."""
    text_lower = text.lower()
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9.#+/\-]*[a-zA-Z0-9]', text_lower)
    keywords = Counter()
    for w in words:
        if w not in STOP_WORDS and len(w) > 1:
            keywords[w] += 1
    # Boost multi-word tech terms
    for term in ['machine learning', 'deep learning', 'artificial intelligence',
                 'computer vision', 'natural language processing', 'rest api',
                 'full stack', 'full-stack', 'devops', 'cloud computing',
                 'object oriented', 'data structures', 'algorithms',
                 'react native', 'node.js', 'next.js', 'tailwind css',
                 'generative ai', 'large language model', 'llm',
                 'firebase', 'google cloud', 'amazon web services']:
        if term in text_lower:
            keywords[term] += 2
    return keywords


def score_text(text, job_keywords):
    """Score a text string against job keywords."""
    text_lower = text.lower()
    score = 0.0
    for keyword, count in job_keywords.items():
        if keyword in text_lower:
            score += count * 2
        for syn_key, syn_list in TECH_SYNONYMS.items():
            if keyword == syn_key or keyword in syn_list:
                for syn in [syn_key] + syn_list:
                    if syn in text_lower:
                        score += count
                        break
    return score


# ══════════════════════════════════════════════════════════════════════════════
# PDF GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class ResumePDFGenerator:
    """Generates ATS-friendly resume PDFs matching the original styling."""

    def __init__(self, output_path):
        self.output_path = output_path
        self.c = canvas.Canvas(output_path, pagesize=A4)
        self.y = PAGE_HEIGHT - MARGIN_TOP
        self.page = 1

    def _check_page_break(self, needed):
        if self.y - needed < MARGIN_BOTTOM:
            self.c.showPage()
            self.page += 1
            self.y = PAGE_HEIGHT - MARGIN_TOP

    def _draw_section_line(self):
        self.c.setStrokeColor(COLOR_LINE)
        self.c.setLineWidth(0.5)
        self.c.line(MARGIN_LEFT, self.y + 2, PAGE_WIDTH - MARGIN_RIGHT, self.y + 2)

    def draw_name(self, name):
        self.c.setFont('Times-Bold', FONT_NAME_SIZE)
        self.c.setFillColor(COLOR_DARK)
        name_width = self.c.stringWidth(name, 'Times-Bold', FONT_NAME_SIZE)
        x = (PAGE_WIDTH - name_width) / 2
        self.c.drawString(x, self.y - FONT_NAME_SIZE, name)
        self.y -= (FONT_NAME_SIZE + 12)

    def draw_contact(self, personal):
        items = []
        for key in ['phone', 'email', 'linkedin', 'github', 'leetcode', 'website']:
            if personal.get(key):
                url = ""
                val = personal[key]
                if key == 'phone':
                    url = f"tel:{val.replace(' ', '')}"
                elif key == 'email':
                    url = f"mailto:{val}"
                else:
                    url = f"https://{val}" if not val.startswith("http") else val
                items.append((val, url))

        line1_items = items[:4]
        line2_items = items[4:]

        self.c.setFont('Helvetica', FONT_CONTACT_SIZE)

        def _calc_width(items_list):
            w = 0
            for i, (val, url) in enumerate(items_list):
                if i > 0:
                    w += self.c.stringWidth(' | ', 'Helvetica', FONT_CONTACT_SIZE)
                w += self.c.stringWidth(val, 'Helvetica', FONT_CONTACT_SIZE)
            return w

        def _draw_centered(items_list):
            total_w = _calc_width(items_list)
            x = (PAGE_WIDTH - total_w) / 2
            for i, (val, url) in enumerate(items_list):
                if i > 0:
                    self.c.setFillColor(COLOR_LIGHT)
                    self.c.drawString(x, self.y - FONT_CONTACT_SIZE, ' | ')
                    x += self.c.stringWidth(' | ', 'Helvetica', FONT_CONTACT_SIZE)
                self.c.setFillColor(COLOR_DARK)
                self.c.drawString(x, self.y - FONT_CONTACT_SIZE, val)
                val_w = self.c.stringWidth(val, 'Helvetica', FONT_CONTACT_SIZE)
                if url:
                    link_rect = (x, self.y - FONT_CONTACT_SIZE - 2, x + val_w, self.y + 2)
                    self.c.linkURL(url, link_rect, relative=0)
                x += val_w

        _draw_centered(line1_items)
        self.y -= (FONT_CONTACT_SIZE + 8)
        if line2_items:
            _draw_centered(line2_items)
            self.y -= (FONT_CONTACT_SIZE + 4)
        self.y -= 6

    def draw_section_header(self, title):
        self._check_page_break(40)
        self.y -= SECTION_SPACING
        self.c.setFont('Times-Bold', FONT_SECTION_SIZE)
        self.c.setFillColor(COLOR_DARK)
        self.c.drawString(MARGIN_LEFT, self.y - FONT_SECTION_SIZE, title.upper())
        self.y -= (FONT_SECTION_SIZE + 4)
        self._draw_section_line()
        self.y -= 8

    def draw_education(self, edu):
        self._check_page_break(50)
        self.c.setFont('Helvetica-Bold', FONT_JOB_TITLE_SIZE)
        self.c.setFillColor(COLOR_DARK)
        self.c.drawString(MARGIN_LEFT, self.y - FONT_JOB_TITLE_SIZE, edu['institution'])
        date_str = f"{edu['start']} \u2013 {edu['end']}"
        self.c.setFont('Helvetica', FONT_SMALL_SIZE)
        self.c.setFillColor(COLOR_MEDIUM)
        date_width = self.c.stringWidth(date_str, 'Helvetica', FONT_SMALL_SIZE)
        self.c.drawString(PAGE_WIDTH - MARGIN_RIGHT - date_width, self.y - FONT_SMALL_SIZE + 1, date_str)
        self.y -= (FONT_JOB_TITLE_SIZE + 4)

        self.c.setFont('Helvetica-Oblique', FONT_SMALL_SIZE)
        self.c.setFillColor(COLOR_MEDIUM)
        self.c.drawString(MARGIN_LEFT, self.y - FONT_SMALL_SIZE, edu['degree'])
        self.c.setFont('Helvetica', FONT_SMALL_SIZE)
        cgpa_str = f"CGPA: {edu['cgpa']}"
        cgpa_width = self.c.stringWidth(cgpa_str, 'Helvetica', FONT_SMALL_SIZE)
        self.c.drawString(PAGE_WIDTH - MARGIN_RIGHT - cgpa_width, self.y - FONT_SMALL_SIZE, cgpa_str)
        self.y -= (FONT_SMALL_SIZE + 8)

    def draw_experience(self, exp):
        self._check_page_break(60)
        self.c.setFont('Helvetica-Bold', FONT_JOB_TITLE_SIZE)
        self.c.setFillColor(COLOR_DARK)
        self.c.drawString(MARGIN_LEFT, self.y - FONT_JOB_TITLE_SIZE, exp['title'])
        date_str = f"{exp['start']} \u2013 {exp['end']}"
        self.c.setFont('Helvetica', FONT_SMALL_SIZE)
        self.c.setFillColor(COLOR_MEDIUM)
        date_width = self.c.stringWidth(date_str, 'Helvetica', FONT_SMALL_SIZE)
        self.c.drawString(PAGE_WIDTH - MARGIN_RIGHT - date_width, self.y - FONT_SMALL_SIZE + 1, date_str)
        self.y -= (FONT_JOB_TITLE_SIZE + 4)

        self.c.setFont('Helvetica-Oblique', FONT_SMALL_SIZE)
        self.c.setFillColor(COLOR_MEDIUM)
        self.c.drawString(MARGIN_LEFT, self.y - FONT_SMALL_SIZE, exp['company'])
        self.y -= (FONT_SMALL_SIZE + COMPANY_SPACING)

        for bullet in exp['bullets']:
            self._check_page_break(20)
            text = bullet['text'] if isinstance(bullet, dict) else bullet
            bold = bullet.get('bold_phrases') if isinstance(bullet, dict) else None
            self._draw_bullet(text, bold_phrases=bold)
            self.y -= BULLET_SPACING

    def draw_project(self, proj):
        self._check_page_break(80)
        self.c.setFont('Helvetica-Bold', FONT_JOB_TITLE_SIZE)
        self.c.setFillColor(COLOR_DARK)
        title_text = proj['title'] + "  |  "
        title_w = self.c.stringWidth(title_text, 'Helvetica-Bold', FONT_JOB_TITLE_SIZE)
        self.c.drawString(MARGIN_LEFT, self.y - FONT_JOB_TITLE_SIZE, title_text)
        self.c.setFont('Helvetica', FONT_SMALL_SIZE)
        self.c.setFillColor(COLOR_DARK)
        self.c.drawString(MARGIN_LEFT + title_w, self.y - FONT_SMALL_SIZE + 1, proj['tech'])

        date_str = f"{proj['start']} \u2013 {proj['end']}" if proj.get('end') else proj['start']
        self.c.setFont('Helvetica', FONT_SMALL_SIZE)
        self.c.setFillColor(COLOR_MEDIUM)
        date_width = self.c.stringWidth(date_str, 'Helvetica', FONT_SMALL_SIZE)
        self.c.drawString(PAGE_WIDTH - MARGIN_RIGHT - date_width, self.y - FONT_SMALL_SIZE + 1, date_str)
        self.y -= (FONT_JOB_TITLE_SIZE + 4)

        links = []
        if proj.get('github'):
            links.append(("GitHub", proj['github']))
        if proj.get('link'):
            links.append(("Demo", proj['link']))
        if links:
            self.c.setFont('Helvetica', FONT_SMALL_SIZE)
            x_offset = MARGIN_LEFT
            for idx, (label, url) in enumerate(links):
                if idx > 0:
                    self.c.setFont('Helvetica', FONT_SMALL_SIZE)
                    self.c.setFillColor(COLOR_MEDIUM)
                    sep = '  |  '
                    self.c.drawString(x_offset, self.y - FONT_SMALL_SIZE, sep)
                    x_offset += self.c.stringWidth(sep, 'Helvetica', FONT_SMALL_SIZE)
                
                display_text = f"{label}: {url}"
                self.c.setFont('Helvetica', FONT_SMALL_SIZE)
                self.c.setFillColor(COLOR_LINK)
                self.c.drawString(x_offset, self.y - FONT_SMALL_SIZE, display_text)
                
                dest_url = url
                if not dest_url.startswith(('http://', 'https://')):
                    dest_url = 'https://' + dest_url
                
                txt_w = self.c.stringWidth(display_text, 'Helvetica', FONT_SMALL_SIZE)
                link_rect = (x_offset, self.y - FONT_SMALL_SIZE - 2, x_offset + txt_w, self.y + 2)
                self.c.linkURL(dest_url, link_rect, relative=0)
                
                x_offset += txt_w
            self.y -= (FONT_SMALL_SIZE + 4)

        for bullet in proj['bullets']:
            self._check_page_break(20)
            text = bullet['text'] if isinstance(bullet, dict) else bullet
            bold = bullet.get('bold_phrases') if isinstance(bullet, dict) else None
            self._draw_bullet(text, bold_phrases=bold)
            self.y -= BULLET_SPACING

    def _draw_bullet(self, text, bold_phrases=None):
        self.c.setFillColor(COLOR_DARK)

        if bold_phrases:
            segments = self._build_segments(text, bold_phrases)
        else:
            segments = [(text, False)]

        # Flatten into word items
        word_items = []
        for seg_text, seg_bold in segments:
            words = seg_text.split(' ')
            for w in words:
                if w:
                    word_items.append((w, seg_bold))

        # Wrap into lines
        lines = []
        current_line = [('\u2022', False)]
        current_width = self.c.stringWidth('\u2022  ', 'Helvetica', FONT_BODY_SIZE)

        for word, is_bold in word_items:
            font = 'Helvetica-Bold' if is_bold else 'Helvetica'
            word_w = self.c.stringWidth(' ' + word, font, FONT_BODY_SIZE)
            if current_width + word_w <= CONTENT_WIDTH:
                current_line.append((word, is_bold))
                current_width += word_w
            else:
                lines.append(current_line)
                current_line = [(word, is_bold)]
                indent_w = self.c.stringWidth('     ', 'Helvetica', FONT_BODY_SIZE)
                current_width = indent_w + self.c.stringWidth(word, font, FONT_BODY_SIZE)
        if current_line:
            lines.append(current_line)

        for line_idx, line_words in enumerate(lines):
            x = MARGIN_LEFT
            if line_idx == 0:
                self.c.setFont('Helvetica', FONT_BODY_SIZE)
                self.c.drawString(x, self.y - FONT_BODY_SIZE, '\u2022')
                x += self.c.stringWidth('\u2022  ', 'Helvetica', FONT_BODY_SIZE)
                draw_words = line_words[1:]
            else:
                x += self.c.stringWidth('     ', 'Helvetica', FONT_BODY_SIZE)
                draw_words = line_words

            for w_idx, (word, is_bold) in enumerate(draw_words):
                font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                self.c.setFont(font, FONT_BODY_SIZE)
                self.c.setFillColor(COLOR_DARK)
                if w_idx > 0:
                    self.c.drawString(x, self.y - FONT_BODY_SIZE, ' ')
                    x += self.c.stringWidth(' ', font, FONT_BODY_SIZE)
                self.c.drawString(x, self.y - FONT_BODY_SIZE, word)
                x += self.c.stringWidth(word, font, FONT_BODY_SIZE)

            self.y -= LINE_HEIGHT

    def _build_segments(self, text, bold_phrases):
        """Split text into (text, is_bold) segments based on matched phrases."""
        text_lower = text.lower()
        bold_positions = []
        for phrase in bold_phrases:
            pattern = r'\b' + re.escape(phrase.lower()) + r'\b'
            for m in re.finditer(pattern, text_lower):
                bold_positions.append((m.start(), m.end()))
        bold_positions.sort()

        # Merge overlapping positions
        merged = []
        for start, end in bold_positions:
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
            else:
                merged.append((start, end))

        segments = []
        cursor = 0
        for start, end in merged:
            if start > cursor:
                segments.append((text[cursor:start], False))
            segments.append((text[start:end], True))
            cursor = end
        if cursor < len(text):
            segments.append((text[cursor:], False))

        return segments

    def draw_skills(self, skills, relevant_skills=None):
        for category, items in skills.items():
            self._check_page_break(25)
            
            self.c.setFont('Helvetica-Bold', FONT_SMALL_SIZE)
            self.c.setFillColor(COLOR_DARK)
            category_prefix = f"{category}:  "
            self.c.drawString(MARGIN_LEFT, self.y - FONT_SMALL_SIZE, category_prefix)
            cat_w = self.c.stringWidth(category_prefix, 'Helvetica-Bold', FONT_SMALL_SIZE)
            
            # Format list of skills as (text, is_bold)
            word_items = []
            for i, skill in enumerate(items):
                sep = ', ' if i > 0 else ''
                is_relevant = relevant_skills and any(
                    skill.lower() in rs.lower() or rs.lower() in skill.lower()
                    for rs in relevant_skills
                )
                word_items.append((sep + skill, is_relevant))

            lines = []
            current_line = []
            current_width = cat_w
            
            for skill_text, is_bold in word_items:
                font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                skill_w = self.c.stringWidth(skill_text, font, FONT_SMALL_SIZE)
                
                if current_width + skill_w <= CONTENT_WIDTH:
                    current_line.append((skill_text, is_bold))
                    current_width += skill_w
                else:
                    if current_line:
                        lines.append(current_line)
                    indent_w = 15
                    clean_text = skill_text.lstrip(', ')
                    clean_w = self.c.stringWidth(clean_text, font, FONT_SMALL_SIZE)
                    current_line = [(clean_text, is_bold)]
                    current_width = indent_w + clean_w
            if current_line:
                lines.append(current_line)
                
            for line_idx, line_items in enumerate(lines):
                if line_idx > 0:
                    self._check_page_break(15)
                
                x = MARGIN_LEFT
                if line_idx == 0:
                    x += cat_w
                else:
                    x += 15
                    
                for skill_text, is_bold in line_items:
                    font = 'Helvetica-Bold' if is_bold else 'Helvetica'
                    self.c.setFont(font, FONT_SMALL_SIZE)
                    self.c.setFillColor(COLOR_DARK)
                    self.c.drawString(x, self.y - FONT_SMALL_SIZE, skill_text)
                    x += self.c.stringWidth(skill_text, font, FONT_SMALL_SIZE)
                
                self.y -= LINE_HEIGHT
            self.y -= 2

    def draw_certifications(self, certs, relevant_certs=None):
        """Draw certifications with right-aligned clickable View links."""
        display_certs = certs
        for cert in display_certs:
            self._check_page_break(18)
            self.c.setFillColor(COLOR_DARK)

            self.c.setFont('Helvetica', FONT_SMALL_SIZE)
            name_text = f"{cert['name']}  \u00b7  {cert['issuer']}"
            if cert.get('date'):
                name_text += f"  |  {cert['date']}"
            
            # Draw the main text left-aligned
            self.c.drawString(MARGIN_LEFT, self.y - FONT_SMALL_SIZE, name_text)

            if cert.get('url'):
                view_text = "View"
                self.c.setFont('Helvetica-Bold', FONT_SMALL_SIZE)
                self.c.setFillColor(COLOR_LINK)
                view_w = self.c.stringWidth(view_text, 'Helvetica-Bold', FONT_SMALL_SIZE)
                
                # Draw the View link right-aligned
                self.c.drawString(PAGE_WIDTH - MARGIN_RIGHT - view_w, self.y - FONT_SMALL_SIZE, view_text)
                
                # Make the link rectangle cover the right-aligned View text
                link_rect = (PAGE_WIDTH - MARGIN_RIGHT - view_w, self.y - FONT_SMALL_SIZE - 3,
                             PAGE_WIDTH - MARGIN_RIGHT, self.y + 5)
                self.c.linkURL(cert['url'], link_rect, relative=0)

            self.y -= (FONT_SMALL_SIZE + 3)

    def save(self):
        self.c.save()


# ══════════════════════════════════════════════════════════════════════════════
# TAILORING LOGIC
# ══════════════════════════════════════════════════════════════════════════════

AUTO_BOLD_PATTERNS = [
    r'\d+[+,]?\s*(?:\+\s*)?(?:global currencies|training images|students|functions|fully functional|mobile applications|weeks?|epochs?|years?|months?|roles|projects?|apps?|APIs?|interns?|candidates|items?|users?|images|tasks|lines|pages|types|devices|platforms)',
    r'\d+%', r'₹[\d,]+', r'\$\d+',
    r'(?:sub-second|cross-platform|production-grade|production-ready|real-time|full-stack|open-source|end-to-end|zero-shot)',
]


def tailor_bullets(bullets, job_keywords, max_bullets=5):
    """Score and rank bullets by relevance to job. Auto-highlights numbers, metrics, tech terms."""
    scored = []
    for bullet in bullets:
        text = bullet['text'] if isinstance(bullet, dict) else bullet
        keywords = bullet.get('keywords', []) if isinstance(bullet, dict) else []
        user_bold = bullet.get('bold_phrases', []) if isinstance(bullet, dict) else []

        text_score = score_text(text, job_keywords)
        kw_score = sum(job_keywords.get(kw.lower(), 0) * 2 for kw in keywords)
        total_score = text_score + kw_score

        bold_phrases = list(user_bold) if user_bold else []

        # Add job-matched keywords
        text_lower = text.lower()
        for keyword in job_keywords:
            if keyword in text_lower and len(keyword) > 2 and keyword not in bold_phrases:
                bold_phrases.append(keyword)
            for syn_key, syn_list in TECH_SYNONYMS.items():
                if keyword == syn_key or keyword in syn_list:
                    for syn in [syn_key] + syn_list:
                        if syn in text_lower and syn not in bold_phrases and len(syn) > 2:
                            bold_phrases.append(syn)
                            break

        # Auto-detect numbers/metrics
        for pattern in AUTO_BOLD_PATTERNS:
            for m in re.finditer(pattern, text, re.IGNORECASE):
                phrase = m.group().strip()
                if phrase and phrase not in bold_phrases:
                    bold_phrases.append(phrase)

        bold_phrases = bold_phrases[:8]

        scored.append({
            'text': text,
            'keywords': keywords,
            'bold_phrases': bold_phrases,
            'score': total_score
        })

    scored.sort(key=lambda x: x['score'], reverse=True)
    return scored[:max_bullets]


def tailor_experience(experience, job_keywords):
    """Tailor experience entries based on job keywords."""
    tailored = []
    for exp in experience:
        tailored_bullets = tailor_bullets(exp['bullets'], job_keywords, 5)
        tailored.append({**exp, 'bullets': tailored_bullets})
    return tailored


def tailor_projects(projects, job_keywords):
    """Tailor and reorder projects by relevance."""
    scored_projects = []
    for proj in projects:
        proj_text = proj['title'] + ' ' + proj['tech']
        for b in proj['bullets']:
            text = b['text'] if isinstance(b, dict) else b
            proj_text += ' ' + text

        score = score_text(proj_text, job_keywords)
        tailored_bullets = tailor_bullets(proj['bullets'], job_keywords, 4)
        scored_projects.append({
            **proj,
            'bullets': tailored_bullets,
            'relevance_score': score
        })

    scored_projects.sort(key=lambda x: x['relevance_score'], reverse=True)
    return scored_projects


def tailor_skills(skills, job_keywords):
    """Identify relevant skills by job match."""
    relevant = []
    for category, items in skills.items():
        for skill in items:
            if score_text(skill, job_keywords) > 0:
                relevant.append(skill)
    return skills, relevant


def tailor_certifications(certs, job_keywords):
    """Reorder certifications by relevance."""
    scored = []
    for cert in certs:
        cert_text = cert['name'] + ' ' + cert['issuer']
        score = score_text(cert_text, job_keywords)
        scored.append((score, cert))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [cert for _, cert in scored]


# ══════════════════════════════════════════════════════════════════════════════
# MAIN GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

def generate_resume(data, job_description=None, output_path='resume.pdf', summary=None):
    """Generate the resume PDF."""
    job_keywords = Counter()
    if job_description:
        job_keywords = extract_keywords(job_description)
        print(f"[+] Extracted {len(job_keywords)} keywords from job description")
        top_kws = job_keywords.most_common(15)
        print(f"[+] Top keywords: {', '.join(f'{k}({v})' for k, v in top_kws)}")

    # Tailor content
    experience = tailor_experience(data['experience'], job_keywords) if job_keywords else data['experience']
    projects = tailor_projects(data['projects'], job_keywords)[:2] if job_keywords else data['projects'][:2]
    skills, relevant_skills = tailor_skills(data['skills'], job_keywords)
    certs = tailor_certifications(data['certifications'], job_keywords) if job_keywords else data['certifications']

    display_summary = summary if summary is not None else data.get('summary', '')

    # Generate PDF
    pdf = ResumePDFGenerator(output_path)

    # Header
    pdf.draw_name(data['personal']['name'])
    pdf.draw_contact(data['personal'])

    # Summary
    if display_summary:
        pdf.draw_section_header('Summary')
        pdf.c.setFont('Helvetica', FONT_BODY_SIZE)
        pdf.c.setFillColor(COLOR_DARK)
        words = display_summary.split(' ')
        line = ''
        for word in words:
            test = line + ' ' + word if line else word
            if pdf.c.stringWidth(test, 'Helvetica', FONT_BODY_SIZE) <= CONTENT_WIDTH:
                line = test
            else:
                pdf.c.drawString(MARGIN_LEFT, pdf.y - FONT_BODY_SIZE, line)
                pdf.y -= LINE_HEIGHT
                line = word
        if line:
            pdf.c.drawString(MARGIN_LEFT, pdf.y - FONT_BODY_SIZE, line)
            pdf.y -= LINE_HEIGHT

    # Education
    pdf.draw_section_header('Education')
    for edu in data['education']:
        pdf.draw_education(edu)

    # Experience
    pdf.draw_section_header('Experience')
    for exp in experience:
        pdf.draw_experience(exp)

    # Projects
    pdf.draw_section_header('Projects')
    for proj in projects:
        pdf.draw_project(proj)

    # Technical Skills
    pdf.draw_section_header('Technical Skills')
    pdf.draw_skills(skills, relevant_skills)

    # Certifications
    pdf.draw_section_header('Certifications')
    pdf.draw_certifications(certs, relevant_skills)

    pdf.save()
    print(f"[+] Resume saved to: {output_path}")

    # Print tailoring report
    if job_keywords:
        print(f"\n{'=' * 60}")
        print("TAILORING REPORT")
        print(f"{'=' * 60}")
        print(f"Job keywords matched: {len([k for k, v in job_keywords.items() if v > 0])}")
        print(f"\nExperience bullets reordered by relevance:")
        for i, exp in enumerate(experience):
            company_short = exp['company'].split('\u2014')[0].strip()
            print(f"  {exp['title']} ({company_short}):")
            for j, b in enumerate(exp['bullets']):
                print(f"    {j+1}. [{b.get('score', 0):.1f}] {b['text'][:80]}...")
        print(f"\nProjects reordered by relevance:")
        for i, proj in enumerate(projects):
            print(f"  {i+1}. [{proj.get('relevance_score', 0):.1f}] {proj['title']}")
        print(f"\nRelevant skills highlighted: {', '.join(relevant_skills[:10])}")
        if len(relevant_skills) > 10:
            print(f"  ...and {len(relevant_skills) - 10} more")
        print(f"{'=' * 60}")

    return output_path


# ══════════════════════════════════════════════════════════════════════════════
# CLI ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description='ATS-Friendly Resume Generator for Shashikumar S',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 resume.py                                    # Interactive prompt
  python3 resume.py --job "Looking for a Python developer..."
  python3 resume.py --job-file job_description.txt
  python3 resume.py --no-summary -o tailored.pdf
        """
    )
    parser.add_argument('--job', type=str, default=None,
                        help='Job description text (inline)')
    parser.add_argument('--job-file', type=str, default=None,
                        help='Path to job description file')
    parser.add_argument('-o', '--output', default='resume.pdf',
                        help='Output PDF path (default: resume.pdf)')
    parser.add_argument('--summary', type=str, default=None,
                        help='Custom summary/objective to use')
    parser.add_argument('--no-summary', action='store_true',
                        help='Omit the summary section')

    args = parser.parse_args()

    # Get job description
    job_description = None
    if args.job:
        job_description = args.job
    elif args.job_file:
        if not os.path.isfile(args.job_file):
            print(f"ERROR: File not found: {args.job_file}")
            sys.exit(1)
        with open(args.job_file, 'r', encoding='utf-8') as f:
            job_description = f.read()
    else:
        # Interactive prompt
        print("=" * 60)
        print("  RESUME GENERATOR — Job Description Input")
        print("=" * 60)
        print("Paste your job description below.")
        print("Press Ctrl+D (or Ctrl+Z on Windows) when done.")
        print("(Or just press Enter twice for default/untailored resume)")
        print("-" * 60)
        try:
            lines = []
            while True:
                line = input()
                lines.append(line)
            job_description = '\n'.join(lines)
        except EOFError:
            job_description = '\n'.join(lines).strip()
            if not job_description:
                job_description = None
                print("\n[+] No job description provided. Generating default resume.")
            else:
                print(f"\n[+] Job description received ({len(job_description)} chars)")

    # Summary handling
    summary = RESUME_DATA.get('summary', '')
    if args.no_summary:
        summary = ''
    elif args.summary:
        summary = args.summary

    # Generate
    print()
    generate_resume(RESUME_DATA, job_description, args.output, summary)
    print()
    print("Done! Open the PDF with any PDF viewer on your phone.")


if __name__ == '__main__':
    main()



