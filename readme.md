# CourseFinder AI Scraper API

A FastAPI + Playwright automation project for scraping program data from CourseFinder AI and exporting complete search results into Excel files.

---

# Features

- FastAPI REST API
- Playwright browser automation
- Persistent login sessions using cookies
- Multi-query search support
- Automatic pagination handling
- Select all records across pages
- Download full Excel exports
- Headless or visible browser execution
- Error handling and retry-safe utilities
- Exporting and Selecting limit is 25 only, So added one by one page export and combine them.

---

# Tech Stack

| Technology | Purpose |
|---|---|
| Python | Backend language |
| FastAPI | API framework |
| Playwright | Browser automation |
| Uvicorn | ASGI server |
| python-dotenv | Environment variable management |

---

# Project Structure

```bash
project/
│
├── app/
│   ├── main.py
│   ├── scraper.py
│   ├── schemas.py
│   └── __init__.py
│
├── downloads/
├── cookies.json
├── .env
├── requirements.txt
└── README.md
```

---

# Installation

## 1. Clone Repository

```bash
git clone <repository-url>

cd <project-folder>
```

---

## 2. Create Virtual Environment

### macOS / Linux

```bash
python3 -m venv venv
```

### Windows

```bash
python -m venv venv
```

---

## 3. Activate Virtual Environment

### macOS / Linux

```bash
source venv/bin/activate
```

### Windows

```bash
venv\Scripts\activate
```

---

## 4. Install Dependencies

```bash
pip install -r requirements.txt
```

---

## 5. Install Playwright Browsers

```bash
playwright install chromium
```

---

# Environment Variables

Create a `.env` file in the project root.

```env
SCRAPER_EMAIL=your_email@example.com
SCRAPER_PASSWORD=your_password

HEADLESS=false

SCRAPER_TIMEOUT=30

DOWNLOADS_DIR=downloads

COOKIES_PATH=cookies.json
```

---

# Running the API

Start the FastAPI development server:

```bash
uvicorn app.main:app --reload
```

API will run at:

```txt
http://127.0.0.1:8000
```

---

# Swagger Documentation

Interactive API documentation:

```txt
http://127.0.0.1:8000/docs
```

---

# API Endpoints

# Search Programs

## Endpoint

```http
POST /search
```

---

## Request Body

```json
{
  "queries": [
    "Master of Accountancy",
    "PhD Accounting"
  ],
  "headless": false
}
```

---

## Response Example

```json
[
  {
    "query": "Master of Accountancy",
    "success": true,
    "filename": "downloads/master_of_accountancy_20260527.xlsx",
    "error": null
  },
  {
    "query": "PhD Accounting",
    "success": true,
    "filename": "downloads/phd_accounting_20260527.xlsx",
    "error": null
  }
]
```

---

# cURL Example

```bash
curl -X POST "http://127.0.0.1:8000/search" \
-H "Content-Type: application/json" \
-d '{
  "queries": [
    "Master of Accountancy",
    "PhD Accounting"
  ],
  "headless": false
}'
```

---

# Scraper Workflow

The scraper performs the following actions:

1. Launch Chromium browser
2. Load saved cookies if available
3. Login to CourseFinder AI
4. Navigate to Search Program page
5. Search provided query
6. Click "Select All" checkbox for current page
7. Navigate pagination using next arrow
8. Repeat until pagination ends
9. Click main "Download" button
10. Open "Select Fields" modal
11. Click "Select All" fields
12. Click "Download to Excel"
13. Save Excel file locally

---

# Downloads

All exported files are saved inside:

```txt
downloads/
```

---

# Cookie Persistence

Cookies are automatically saved to:

```txt
cookies.json
```

This prevents repeated login sessions.

---

# Headless Mode

## Run Hidden Browser

```json
{
  "headless": true
}
```

---

## Run Visible Browser

```json
{
  "headless": false
}
```

---

# Common Issues

# Playwright Browser Missing

## Error

```txt
Executable doesn't exist
```

## Fix

```bash
playwright install chromium
```

---

# Timeout Errors

Increase timeout value inside `.env`:

```env
SCRAPER_TIMEOUT=60
```

---

# Login Failures

Verify:

- Correct email
- Correct password
- Stable internet connection
- CourseFinder AI availability

---

# Development

## Run Formatter

```bash
black .
```

---

## Run Linter

```bash
flake8 .
```

---

# Example requirements.txt

```txt
fastapi
uvicorn
playwright
python-dotenv
pydantic
```

---

# Security Notes

- Never commit `.env`
- Never expose credentials publicly
- Use environment variables in production
- Rotate credentials periodically

---

# Future Improvements

- Async Playwright support
- Docker containerization
- Queue-based scraping
- Background task processing
- WebSocket progress updates
- CAPTCHA handling
- Proxy support
- Cloud deployment

---

# License

MIT License

---

# Author

Built with:
- FastAPI
- Playwright
- Python Automation